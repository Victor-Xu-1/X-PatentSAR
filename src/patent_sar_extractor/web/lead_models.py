"""Bounded research-prioritization DTO; selection never proves a clinical lead."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .dto import DTO

LEAD_POLICY_VERSION: Literal["2"] = "2"

LeadStatus = Literal[
    "not_run", "stale", "selected", "not_selected", "ineligible", "unranked"
]
LeadScore = Annotated[float, Field(ge=0, le=100, strict=True)]
LeadFraction = Annotated[float, Field(ge=0, le=1, strict=True)]
LeadComponent = Literal[
    "potency", "coverage", "admet", "physchem", "evidence", "diversity"
]


class LeadAssessment(DTO):
    status: LeadStatus = "not_run"
    rank: int | None = Field(default=None, ge=1, le=10, strict=True)
    score: LeadScore | None = None
    activity_coverage: LeadFraction = 0.0
    components: dict[LeadComponent, LeadScore] = Field(
        default_factory=dict, max_length=6
    )
    reasons: list[str] = Field(default_factory=list, max_length=12)
    warnings: list[str] = Field(default_factory=list, max_length=12)
    scaffold: str | None = Field(default=None, max_length=2048, strict=True)
    nearest_similarity: LeadFraction | None = None
    risk_review_required: bool = Field(default=False, strict=True)
    policy_version: Literal["2"] = LEAD_POLICY_VERSION
    review_only: Literal[True] = True

    @field_validator("reasons", "warnings")
    @classmethod
    def bounded_messages(cls, values: list[str]) -> list[str]:
        if any(
            not value or len(value) > 300 or any(ord(char) < 32 for char in value)
            for value in values
        ):
            raise ValueError("Lead messages must be nonempty bounded single lines")
        return values

    @model_validator(mode="after")
    def selection_identity(self) -> LeadAssessment:
        if self.status == "selected":
            if self.rank is None or self.score is None:
                raise ValueError("Selected candidates require both rank and score")
        elif self.rank is not None:
            raise ValueError("Only selected candidates may carry a Lead rank")
        return self
