"""Bounded additive presentation metadata, not an activity/artifact schema."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .dto import DTO

RankKind = Literal["numeric", "plus", "letter", "unknown"]
RankDirection = Literal["lower", "higher", "unknown"]
RankValue = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class ActivityStrengthScale(DTO):
    kind: RankKind
    direction: RankDirection
    rule: str = Field(min_length=1, max_length=64)
    eligible: int = Field(ge=0, le=50_000_000, strict=True)
    excluded: int = Field(ge=0, le=50_000_000, strict=True)
    distinct: int = Field(ge=0, le=50_000, strict=True)
    strong_boundary: RankValue | None
    medium_boundary: RankValue | None

    @model_validator(mode="after")
    def check_bounds(self) -> ActivityStrengthScale:
        if self.distinct > self.eligible or (self.eligible and not self.distinct):
            raise ValueError("Distinct values exceed eligible observations")
        if self.direction == "unknown" or not self.eligible:
            if self.strong_boundary is not None or self.medium_boundary is not None:
                raise ValueError("Unavailable ranking cannot carry cutoffs")
        elif self.strong_boundary is None or self.medium_boundary is None:
            raise ValueError("Available ranking requires both cutoffs")
        elif (
            self.direction == "lower" and self.strong_boundary > self.medium_boundary
        ) or (
            self.direction == "higher" and self.strong_boundary < self.medium_boundary
        ):
            raise ValueError("Ranking cutoffs oppose the direction")
        if self.kind == "unknown" and self.direction != "unknown":
            raise ValueError("Unknown scalar type cannot have an ordering")
        if self.kind in {"plus", "letter"}:
            minimum, maximum = (1, 8) if self.kind == "plus" else (0, 25)
            if any(
                value is not None
                and (not value.is_integer() or not minimum <= value <= maximum)
                for value in (self.strong_boundary, self.medium_boundary)
            ):
                raise ValueError("Grade cutoffs must be actual ordinal levels")
        return self
