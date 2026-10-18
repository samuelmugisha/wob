"""Citation verification (spec §5.3, §13: 100% of citation IDs and passages must resolve).

A citation is valid only if its passage is in *this* finalist's knowledge base (indexed, not
withdrawn) and the quoted span really occurs in that passage.
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

PUNCTUATION = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def normalise(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(PUNCTUATION)
    return re.sub(r"\s+", " ", value).strip().casefold()


@dataclass(frozen=True)
class Citation:
    chunk_id: uuid.UUID
    quote: str


@dataclass(frozen=True)
class CitationCheck:
    chunk_id: uuid.UUID
    quote: str
    valid: bool
    reason: str | None = None
    document_id: uuid.UUID | None = None
    filename: str | None = None
    page_number: int | None = None


def verify_citations(
    session: Session, finalist_category_id: uuid.UUID, citations: list[Citation]
) -> list[CitationCheck]:
    rows = session.execute(
        text(
            "SELECT id, document_id, filename, page_number, content FROM knowledge_base_chunks "
            "WHERE finalist_category_id = :fc AND id = ANY(:ids)"
        ),
        {"fc": finalist_category_id, "ids": [c.chunk_id for c in citations]},
    ).mappings()
    passages = {row["id"]: row for row in rows}

    checks = []
    for citation in citations:
        passage = passages.get(citation.chunk_id)
        quote = normalise(citation.quote)
        if passage is None:
            checks.append(
                CitationCheck(
                    citation.chunk_id,
                    citation.quote,
                    False,
                    "passage is not in this finalist's knowledge base",
                )
            )
            continue
        details = {
            "document_id": passage["document_id"],
            "filename": passage["filename"],
            "page_number": passage["page_number"],
        }
        if not quote:
            checks.append(
                CitationCheck(citation.chunk_id, citation.quote, False, "empty quote", **details)
            )
        elif quote not in normalise(passage["content"]):
            checks.append(
                CitationCheck(
                    citation.chunk_id,
                    citation.quote,
                    False,
                    "quoted text does not appear in the passage",
                    **details,
                )
            )
        else:
            checks.append(CitationCheck(citation.chunk_id, citation.quote, True, **details))
    return checks
