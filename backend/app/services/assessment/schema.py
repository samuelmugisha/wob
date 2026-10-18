from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    ref: str = Field(description="P# for a submitted passage or S# for an accepted public source")
    quote: str = Field(description="Text copied exactly from that passage or source")


class CriterionRating(BaseModel):
    rating: Literal[1, 2, 3, 4, 5] = Field(description="Official committee scale, 1 to 5")
    rationale: str = Field(description="Why this rating, point by point, citing the evidence")
    supporting: list[Citation]
    contradicting: list[Citation]
    limitations: str | None = Field(
        description="Gaps or caveats in the evidence for this criterion"
    )
    sufficiency: Literal["sufficient", "limited", "insufficient"]
    review_required: bool
    review_reasons: list[str]
