"""Inputs for one (finalist, criterion) assessment, and checks on what comes back (spec §7.1)."""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Claim,
    ClaimEvidence,
    ExternalSource,
    ReviewOutcome,
    RubricCriterion,
    RubricStatus,
)
from app.services.assessment.schema import Citation, CriterionRating
from app.services.citations import normalise
from app.services.retrieval import RetrievalResult, Retriever, criterion_query


@dataclass(frozen=True)
class Evidence:
    ref: str
    label: str
    text: str
    chunk_id: uuid.UUID | None = None
    external_source_id: uuid.UUID | None = None


@dataclass
class AssessmentInput:
    evidence: dict[str, Evidence]
    claims: list[tuple[str, str, str]]
    retrieval: RetrievalResult


def build_input(
    session: Session,
    retriever: Retriever,
    finalist_category_id: uuid.UUID,
    criterion: RubricCriterion,
) -> AssessmentInput:
    query = criterion_query(criterion.name, criterion.description, criterion.evidence_expectations)
    retrieval = retriever.search(session, finalist_category_id, query)
    evidence: dict[str, Evidence] = {}
    for i, p in enumerate(retrieval.passages, start=1):
        pages = f", p. {p.page_start}" if p.page_start else ""
        label = f"{p.filename}{pages}" + (f", {p.section}" if p.section else "")
        evidence[f"P{i}"] = Evidence(
            f"P{i}", label.replace('"', "'"), p.content, chunk_id=p.chunk_id
        )

    sources = session.scalars(
        select(ExternalSource)
        .join(ClaimEvidence, ClaimEvidence.external_source_id == ExternalSource.id)
        .join(Claim, Claim.id == ClaimEvidence.claim_id)
        .where(
            ExternalSource.finalist_category_id == finalist_category_id,
            ExternalSource.reviewer_outcome == ReviewOutcome.ACCEPTED,
            Claim.superseded_at.is_(None),
        )
        .distinct()
        .order_by(ExternalSource.created_at)
    ).all()
    for i, s in enumerate(sources, start=1):
        label = f"{s.publisher}, {s.url}".replace('"', "'")
        evidence[f"S{i}"] = Evidence(f"S{i}", label, s.evidence_passage, external_source_id=s.id)

    claims = [
        (c.wording, c.status.value, c.claim_type or "other")
        for c in session.scalars(
            select(Claim)
            .where(
                Claim.finalist_category_id == finalist_category_id, Claim.superseded_at.is_(None)
            )
            .order_by(Claim.claim_type, Claim.wording)
        )
    ]
    return AssessmentInput(evidence, claims, retrieval)


@dataclass
class CheckedRating:
    rating: CriterionRating
    supporting: list[tuple[Evidence, str]] = field(default_factory=list)
    contradicting: list[tuple[Evidence, str]] = field(default_factory=list)
    discarded: list[dict[str, Any]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def review_required(self) -> bool:
        return self.rating.review_required or bool(self.flags)


def check_rating(
    rating: CriterionRating, data: AssessmentInput, rubric_status: RubricStatus
) -> CheckedRating:
    checked = CheckedRating(rating)

    def verify(citations: list[Citation], into: list[tuple[Evidence, str]]) -> None:
        seen = set()
        for c in citations:
            source = data.evidence.get(c.ref.strip().upper())
            if source is None:
                reason = f"unknown reference {c.ref!r}"
            elif not normalise(c.quote) or normalise(c.quote) not in normalise(source.text):
                reason = "quote not found in the cited evidence"
            else:
                key = (source.ref, normalise(c.quote))
                if key not in seen:
                    seen.add(key)
                    into.append((source, c.quote.strip()))
                continue
            checked.discarded.append({"ref": c.ref, "quote": c.quote, "reason": reason})

    verify(rating.supporting, checked.supporting)
    verify(rating.contradicting, checked.contradicting)

    if rating.rating >= 2 and not checked.supporting:
        checked.flags.append("uncited_rating")
    if checked.discarded:
        checked.flags.append("citations_discarded")
    if checked.contradicting:
        checked.flags.append("contradicting_evidence")
    checked.flags += [f"retrieval:{f}" for f in data.retrieval.flags]
    if rubric_status != RubricStatus.FROZEN:
        checked.flags.append("rubric_not_frozen")
    return checked
