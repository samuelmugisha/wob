"""External research (FR-13): findings are kept only if their quote is in a page Claude
actually fetched during the run. Everything else is discarded and reported."""

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.services.citations import PUNCTUATION, normalise
from app.services.claims.extraction import parse_period
from app.services.research.llm import FetchedPage, ResearchResult

CONTEXT_CHARS = 280


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _collapse(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(PUNCTUATION)
    return re.sub(r"\s+", " ", value).strip()


def passage_around(text: str, quote: str) -> str | None:
    """The quote with surrounding context from the page, or None if it is not there."""
    collapsed = _collapse(text)
    needle = _collapse(quote).lower()
    start = collapsed.lower().find(needle)
    if start < 0 or not needle:
        return None
    end = start + len(needle)
    before = collapsed[max(0, start - CONTEXT_CHARS) : start]
    after = collapsed[end : end + CONTEXT_CHARS]
    return (
        ("…" if start > CONTEXT_CHARS else "")
        + before
        + collapsed[start:end]
        + after
        + ("…" if end + CONTEXT_CHARS < len(collapsed) else "")
    )


@dataclass
class VerifiedFinding:
    claim_id: uuid.UUID
    relation: str
    url: str
    publisher: str
    title: str | None
    published_at: Any
    source_type: str
    quote: str
    passage: str
    content_sha256: str
    retrieved_at: datetime
    identity_confidence: str
    identity_notes: str


@dataclass
class ResearchOutcome:
    findings: list[VerifiedFinding] = field(default_factory=list)
    not_found: list[dict[str, Any]] = field(default_factory=list)
    identity_concerns: list[str] = field(default_factory=list)
    discarded: list[dict[str, Any]] = field(default_factory=list)


def verify_findings(result: ResearchResult, claim_refs: dict[str, uuid.UUID]) -> ResearchOutcome:
    pages: dict[str, FetchedPage] = {canonical_url(p.url): p for p in result.pages}
    outcome = ResearchOutcome(identity_concerns=[c for c in result.output.identity_concerns if c])
    seen: set[tuple] = set()

    for finding in result.output.findings:
        claim_id = claim_refs.get(finding.claim_ref.strip().upper())
        page = pages.get(canonical_url(finding.url))
        reason = None
        passage = None
        if claim_id is None:
            reason = f"unknown claim reference {finding.claim_ref!r}"
        elif urlsplit(finding.url).scheme not in ("http", "https"):
            reason = "not a web URL"
        elif page is None:
            reason = "the page was not fetched during research, so the quote can't be checked"
        elif not normalise(finding.quote):
            reason = "empty quote"
        else:
            passage = passage_around(page.text, finding.quote)
            if passage is None:
                reason = "quote not found in the fetched page"
        if reason:
            outcome.discarded.append(
                {
                    "claim_ref": finding.claim_ref,
                    "url": finding.url,
                    "quote": finding.quote,
                    "reason": reason,
                }
            )
            continue

        key = (claim_id, canonical_url(finding.url), finding.relation, normalise(finding.quote))
        if key in seen:
            continue
        seen.add(key)
        published, _ = parse_period(finding.published_date)
        retrieved = _parse_time(page.retrieved_at)
        outcome.findings.append(
            VerifiedFinding(
                claim_id=claim_id,
                relation=finding.relation,
                url=finding.url.strip(),
                publisher=finding.publisher.strip() or urlsplit(finding.url).netloc,
                title=finding.title or page.title,
                published_at=published,
                source_type=finding.source_type,
                quote=finding.quote.strip(),
                passage=passage,
                content_sha256=hashlib.sha256(page.text.encode()).hexdigest(),
                retrieved_at=retrieved,
                identity_confidence=finding.identity_confidence,
                identity_notes=finding.identity_notes.strip(),
            )
        )

    for item in result.output.not_found:
        if item.claim_ref.strip().upper() in claim_refs:
            outcome.not_found.append(
                {"claim_id": str(claim_refs[item.claim_ref.strip().upper()]), "note": item.note}
            )
    return outcome


def _parse_time(value: str | None) -> datetime:
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)
