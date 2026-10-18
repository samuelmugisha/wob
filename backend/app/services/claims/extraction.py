"""Claim extraction (FR-06): passages → LLM → claims whose every quote is verified.

The LLM sees one finalist's indexed passages under short ids (P1, P2, ...). Its output is
never trusted directly: each quote must occur in the passage it cites (after normalising case,
whitespace and typographic punctuation), and a claim with no verifiable supporting quote is
discarded and reported. This is what enforces "extract only supported claims" (spec §10.1).
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.prompts.claim_extraction import SYSTEM_PROMPT, user_prompt
from app.services.citations import normalise
from app.services.claims.llm import ClaimLLM, OutputTruncated
from app.services.claims.schema import ClaimExtractionOutput, EvidenceQuote, ExtractedClaim

# Our token counts come from cl100k; Claude's tokenizer can count up to ~1.35x as many.
TOKENIZER_SAFETY = 1.35
_PERIOD = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")


@dataclass(frozen=True)
class Passage:
    pid: str
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_start: int | None
    page_end: int | None
    section: str | None
    content: str
    tokens: int

    @property
    def source(self) -> str:
        parts = [self.filename]
        if self.page_start:
            pages = (
                f"{self.page_start}"
                if self.page_end in (None, self.page_start)
                else (f"{self.page_start}-{self.page_end}")
            )
            parts.append(f"p. {pages}")
        if self.section:
            parts.append(self.section)
        return ", ".join(parts).replace('"', "'")

    def cite(self, quote: str) -> dict[str, Any]:
        return {
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "filename": self.filename,
            "page": self.page_start,
            "quote": quote,
        }


def load_passages(session: Session, finalist_category_id: uuid.UUID) -> list[Passage]:
    rows = session.execute(
        text(
            "SELECT id, document_id, filename, page_number, metadata->>'page_end' AS page_end, "
            "section, content, token_count FROM knowledge_base_chunks "
            "WHERE finalist_category_id = :fc ORDER BY filename, document_id, chunk_index"
        ),
        {"fc": finalist_category_id},
    ).mappings()
    return [
        Passage(
            pid=f"P{i}",
            chunk_id=row["id"],
            document_id=row["document_id"],
            filename=row["filename"],
            page_start=row["page_number"],
            page_end=int(row["page_end"]) if row["page_end"] else row["page_number"],
            section=row["section"],
            content=row["content"],
            tokens=row["token_count"] or len(row["content"]) // 3,
        )
        for i, row in enumerate(rows, start=1)
    ]


def make_batches(passages: list[Passage], budget_tokens: int) -> list[list[Passage]]:
    """Greedy batches whose (Claude-adjusted) token total stays under the budget. Documents
    stay together where possible because passages are ordered by document."""
    batches: list[list[Passage]] = []
    current: list[Passage] = []
    used = 0.0
    for passage in passages:
        cost = passage.tokens * TOKENIZER_SAFETY
        if current and used + cost > budget_tokens:
            batches.append(current)
            current, used = [], 0.0
        current.append(passage)
        used += cost
    if current:
        batches.append(current)
    return batches


def parse_period(value: str | None) -> tuple[date | None, str | None]:
    """'2019' → (2019-01-01, 'year'); '2019-03' → month; '2019-03-14' → day; else (None, None)."""
    if not value:
        return None, None
    match = _PERIOD.match(value.strip())
    if not match:
        return None, None
    year, month, day = match.groups()
    try:
        parsed = date(int(year), int(month or 1), int(day or 1))
    except ValueError:
        return None, None
    return parsed, "day" if day else "month" if month else "year"


@dataclass
class ValidatedClaim:
    claim: ExtractedClaim
    supporting: list[tuple[Passage, str]]
    contradicting: list[tuple[Passage, str]]


@dataclass
class ExtractionOutcome:
    claims: list[ValidatedClaim] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    discarded: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    served_by: list[str] = field(default_factory=list)
    batches: int = 0


class ClaimExtractor:
    def __init__(self, llm: ClaimLLM, batch_tokens: int) -> None:
        self.llm = llm
        self.batch_tokens = batch_tokens

    def extract(self, nominee: str, category: str, passages: list[Passage]) -> ExtractionOutcome:
        outcome = ExtractionOutcome()
        outputs: list[ClaimExtractionOutput] = []
        pending = make_batches(passages, self.batch_tokens)
        while pending:
            batch = pending.pop(0)
            prompt = user_prompt(nominee, category, [(p.pid, p.source, p.content) for p in batch])
            try:
                result = self.llm.extract(SYSTEM_PROMPT, prompt)
            except OutputTruncated:
                if len(batch) == 1:
                    raise
                half = len(batch) // 2  # too many claims for one response: split and retry
                pending[:0] = [batch[:half], batch[half:]]
                continue
            outcome.batches += 1
            outputs.append(result.output)
            if result.served_by not in outcome.served_by:
                outcome.served_by.append(result.served_by)
            for key, value in result.usage.items():
                outcome.usage[key] = outcome.usage.get(key, 0) + value

        _validate(outputs, {p.pid: p for p in passages}, outcome)
        return outcome


def _check(
    quote: EvidenceQuote, passages: dict[str, Passage], discarded: list[dict], context: str
) -> tuple[Passage, str] | None:
    passage = passages.get(quote.passage_id.strip().upper())
    reason = None
    if passage is None:
        reason = f"unknown passage id {quote.passage_id!r}"
    elif not normalise(quote.quote):
        reason = "empty quote"
    elif normalise(quote.quote) not in normalise(passage.content):
        reason = "quote not found in the cited passage"
    if reason:
        discarded.append(
            {
                "kind": "quote",
                "context": context,
                "passage_id": quote.passage_id,
                "quote": quote.quote,
                "reason": reason,
            }
        )
        return None
    return passage, quote.quote.strip()


def _validate(
    outputs: list[ClaimExtractionOutput], passages: dict[str, Passage], outcome: ExtractionOutcome
) -> None:
    merged: dict[str, ValidatedClaim] = {}
    for output in outputs:
        for claim in output.claims:
            supporting = [
                c
                for q in claim.supporting_evidence
                if (c := _check(q, passages, outcome.discarded, claim.statement))
            ]
            contradicting = [
                c
                for q in claim.contradicting_evidence
                if (c := _check(q, passages, outcome.discarded, claim.statement))
            ]
            if not supporting:
                outcome.discarded.append(
                    {
                        "kind": "claim",
                        "statement": claim.statement,
                        "reason": "no supporting quote could be verified against the evidence",
                    }
                )
                continue
            key = normalise(claim.statement)
            if key in merged:  # the same claim from another batch: merge its evidence
                _extend(merged[key].supporting, supporting)
                _extend(merged[key].contradicting, contradicting)
            else:
                merged[key] = ValidatedClaim(claim, _unique(supporting), _unique(contradicting))

        for contradiction in output.contradictions:
            evidence = [
                c
                for q in contradiction.evidence
                if (c := _check(q, passages, outcome.discarded, contradiction.description))
            ]
            if len(evidence) >= 2 or (evidence and len(contradiction.evidence) == 1):
                outcome.contradictions.append(
                    {
                        "description": contradiction.description,
                        "evidence": [p.cite(q) for p, q in evidence],
                    }
                )
            else:
                outcome.discarded.append(
                    {
                        "kind": "contradiction",
                        "statement": contradiction.description,
                        "reason": "its evidence could not be verified on both sides",
                    }
                )
        for item in output.missing_information:
            if item.strip() and item.strip() not in outcome.missing_information:
                outcome.missing_information.append(item.strip())
    outcome.claims = list(merged.values())


def _unique(items: list[tuple[Passage, str]]) -> list[tuple[Passage, str]]:
    seen: set[tuple[uuid.UUID, str]] = set()
    result = []
    for passage, quote in items:
        key = (passage.chunk_id, normalise(quote))
        if key not in seen:
            seen.add(key)
            result.append((passage, quote))
    return result


def _extend(target: list[tuple[Passage, str]], items: list[tuple[Passage, str]]) -> None:
    target[:] = _unique(target + items)
