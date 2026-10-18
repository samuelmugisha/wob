import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import ClaimStatus, EvidenceRelation, EvidenceSufficiency, JobStatus, QualityLevel


class ResolutionOut(BaseModel):
    resolution: str
    resolved_by: str
    created_at: datetime


class ExtractionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: JobStatus
    llm_model: str
    served_by_models: list[str]
    prompt_version: str
    batches: int
    usage: dict[str, Any]
    claims_created: int
    claims_carried_forward: int
    contradictions: list[dict[str, Any]]
    contradiction_resolutions: dict[int, ResolutionOut] = {}
    missing_information: list[str]
    discarded: list[dict[str, Any]]
    attempts: int
    error: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    completed_at: datetime | None


class ClaimEvidenceOut(BaseModel):
    relation: EvidenceRelation
    quote: str
    chunk_id: uuid.UUID | None
    document_id: uuid.UUID | None
    filename: str | None
    page: int | None
    document_withdrawn: bool
    external_source_id: uuid.UUID | None = None
    url: str | None = None
    publisher: str | None = None


class ReviewOut(BaseModel):
    id: uuid.UUID
    reviewer: str
    reviewer_role: str
    previous_status: ClaimStatus | None
    decision: ClaimStatus
    notes: str | None
    sufficiency: EvidenceSufficiency | None
    credibility: QualityLevel | None
    carried_forward: bool
    created_at: datetime


class ReviewIn(BaseModel):
    decision: ClaimStatus
    expected_status: ClaimStatus = Field(
        description="The status the reviewer saw; the review is rejected if it has changed"
    )
    notes: str | None = Field(default=None, max_length=4000)
    sufficiency: EvidenceSufficiency | None = None
    credibility: QualityLevel | None = None


class ResolutionIn(BaseModel):
    resolution: str = Field(min_length=3, max_length=4000)


class ClaimOut(BaseModel):
    id: uuid.UUID
    statement: str
    claim_type: str | None
    entity: str | None
    role: str | None
    period_start: date | None
    period_start_precision: str | None
    period_end: date | None
    period_end_precision: str | None
    period_text: str | None
    quantitative_outcomes: list[dict[str, Any]]
    limitations: str | None
    status: ClaimStatus
    evidence: list[ClaimEvidenceOut]
    supporting_documents: int
    independent_sources: int = 0
    latest_review: ReviewOut | None = None
    review_count: int = 0


class ClaimsOut(BaseModel):
    extraction: dict[str, Any]
    verification: dict[str, Any]
    latest_run: ExtractionRunOut | None
    claims: list[ClaimOut]


class ExtractRequestOut(BaseModel):
    run: ExtractionRunOut
    warnings: list[str]
