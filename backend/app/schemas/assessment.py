import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import AssessmentStatus, JobStatus, RubricStatus, WeightingMode


class CriterionIn(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    evidence_expectations: str | None = Field(default=None, max_length=2000)
    weight: Decimal | None = Field(default=None, gt=0, le=100)


class RubricIn(BaseModel):
    use_template: bool = False
    criteria: list[CriterionIn] = []
    weighting: WeightingMode = WeightingMode.EQUAL
    notes: str | None = Field(default=None, max_length=4000)


class UnfreezeIn(BaseModel):
    reason: str = Field(min_length=1, max_length=4000)


class CriterionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str
    evidence_expectations: str | None
    weight: Decimal | None
    position: int


class RubricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    status: RubricStatus
    weighting: WeightingMode
    notes: str | None
    approved_at: datetime | None
    frozen_at: datetime | None
    created_at: datetime
    criteria: list[CriterionOut]


class AssessmentRunIn(BaseModel):
    category_id: uuid.UUID
    # "human": no AI; reviewers enter every rating (e.g. while AI processing is not approved).
    mode: Literal["ai", "human"] = "ai"


class HumanRatingIn(BaseModel):
    run_id: uuid.UUID
    finalist_id: uuid.UUID
    criterion_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=10, max_length=4000)
    sufficiency: Literal["sufficient", "limited", "insufficient"]


class AssessmentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    rubric_version_id: uuid.UUID
    rubric_status: RubricStatus | None
    status: JobStatus
    llm_model: str
    served_by_models: list[str]
    prompt_version: str
    embedding_model: str
    reranker_model: str | None
    retrieval_config: dict[str, Any]
    items_total: int
    items_done: int
    skipped: list[dict[str, Any]] = []
    usage: dict[str, Any]
    attempts: int
    error: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    completed_at: datetime | None


class AssessmentCitationOut(BaseModel):
    relation: str
    quote: str
    document_id: uuid.UUID | None = None
    filename: str | None = None
    page: int | None = None
    url: str | None = None
    publisher: str | None = None


class CriterionAssessmentOut(BaseModel):
    id: uuid.UUID
    criterion_id: uuid.UUID
    criterion_code: str
    criterion_name: str
    rating: int
    reviewer_rating: int | None
    effective_rating: int
    rationale: str
    limitations: str | None
    sufficiency: str
    flags: list[str]
    review_required: bool
    status: AssessmentStatus
    source: str = "ai"
    review_notes: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    citations: list[AssessmentCitationOut]
    discarded_citations: list[dict[str, Any]]


class CandidateAssessmentsOut(BaseModel):
    assessment: dict[str, Any]
    run: AssessmentRunOut | None
    rubric: RubricOut | None
    items: list[CriterionAssessmentOut]
    # True while the viewer is a blind rater in an open calibration study (FR-15).
    hidden_for_calibration: bool = False


class AssessmentReviewIn(BaseModel):
    decision: AssessmentStatus
    adjusted_rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=4000)


class RankingIn(BaseModel):
    category_id: uuid.UUID
    run_id: uuid.UUID | None = None


class RankingEntryOut(BaseModel):
    finalist_id: uuid.UUID
    finalist_category_id: uuid.UUID
    full_name: str
    organisation: str | None
    score: str | None
    score_display: str | None
    points_display: str | None
    rank: int | None
    is_tie: bool
    criteria_assessed: int
    criteria_total: int
    missing_criteria: list[str]
    unreviewed_criteria: list[str]
    ratings: dict[str, int | None]


class RankingOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    created_at: datetime
    rubric_version: int
    rubric_status: RubricStatus
    production: bool
    weighting: WeightingMode
    calculation_version: str
    is_provisional: bool
    criteria: list[CriterionOut]
    entries: list[RankingEntryOut]
    close_results: list[dict[str, Any]]
    disclaimer: str


class CategoryRankingsOut(BaseModel):
    assessment: dict[str, Any]
    rubric: RubricOut | None
    latest_run: AssessmentRunOut | None
    ranking: RankingOut | None
    hidden_for_calibration: bool = False
    calibration: dict[str, Any] | None = None  # latest closed calibration study
