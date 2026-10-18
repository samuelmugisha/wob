"""Structured output the claim extractor must return (validated by Pydantic and, on the
Claude API, enforced as a JSON schema)."""

from typing import Literal

from pydantic import BaseModel, Field

ClaimType = Literal[
    "position",
    "achievement",
    "outcome",
    "award",
    "qualification",
    "membership",
    "advocacy",
    "other",
]


class EvidenceQuote(BaseModel):
    passage_id: str = Field(description="Id of the passage the quote comes from, e.g. P3")
    quote: str = Field(description="Text copied exactly, character for character, from it")


class QuantitativeOutcome(BaseModel):
    metric: str = Field(description="What was measured, e.g. 'women appointed to boards'")
    value: str = Field(description="The figure exactly as stated, e.g. '12' or '40%'")
    unit: str | None = Field(description="Unit or currency if stated, else null")


class ExtractedClaim(BaseModel):
    statement: str = Field(description="One self-contained factual claim about the nominee")
    claim_type: ClaimType
    entity: str | None = Field(description="Organisation or body the claim concerns, if any")
    role: str | None = Field(description="Position or role held, if the claim states one")
    period_start: str | None = Field(
        description="Start as YYYY, YYYY-MM or YYYY-MM-DD, only if the evidence states it"
    )
    period_end: str | None = Field(
        description="End as YYYY, YYYY-MM or YYYY-MM-DD, only if stated; null if ongoing"
    )
    period_text: str | None = Field(description="The period as worded in the evidence")
    quantitative_outcomes: list[QuantitativeOutcome]
    supporting_evidence: list[EvidenceQuote] = Field(description="At least one quote")
    contradicting_evidence: list[EvidenceQuote]
    limitations: str | None = Field(
        description="Caveats a judge should know, e.g. only self-reported, vague dates"
    )


class Contradiction(BaseModel):
    description: str
    evidence: list[EvidenceQuote]


class ClaimExtractionOutput(BaseModel):
    claims: list[ExtractedClaim]
    contradictions: list[Contradiction]
    missing_information: list[str] = Field(
        description="Information a judge would expect but the evidence does not provide"
    )
