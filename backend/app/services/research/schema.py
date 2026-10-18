"""Structured output of an external research run."""

from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal[
    "official_registry",
    "regulator",
    "organisation_website",
    "annual_report",
    "news_media",
    "professional_body",
    "other",
]


class Finding(BaseModel):
    claim_ref: str = Field(description="The claim this source concerns, e.g. C3")
    relation: Literal["supports", "contradicts"]
    url: str = Field(description="URL of a page you fetched with web_fetch")
    publisher: str = Field(description="Organisation that published the page")
    title: str | None
    published_date: str | None = Field(
        description="Publication date as YYYY, YYYY-MM or YYYY-MM-DD if the page shows it"
    )
    source_type: SourceType
    quote: str = Field(description="Text copied exactly from the fetched page")
    identity_confidence: Literal["high", "medium", "low"] = Field(
        description="How certain it is that the page is about this nominee, not a namesake"
    )
    identity_notes: str = Field(description="What links the page to the nominee")


class NotFound(BaseModel):
    claim_ref: str
    note: str = Field(description="What was searched; never a judgement about the claim")


class ResearchOutput(BaseModel):
    findings: list[Finding]
    not_found: list[NotFound]
    identity_concerns: list[str] = Field(
        description="Namesakes or ambiguities a reviewer should know about"
    )
