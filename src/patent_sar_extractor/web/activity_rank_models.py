"""Bounded additive presentation metadata, not an activity/artifact schema."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, model_validator

from .dto import DTO

if TYPE_CHECKING:
    from ..core.potency_bands import PotencyScale

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
    method: Literal["tied_terciles", "tenth_decade"] = "tied_terciles"
    status: Literal["ready", "insufficient", "ambiguous", "limit", "unsupported"] = (
        "ready"
    )
    boundary_inclusive: bool = Field(default=True, strict=True)
    population: int | None = Field(default=None, ge=0, le=50_000, strict=True)
    anchor_rank: Literal[10] | None = None
    anchor_lower: RankValue | None = None
    anchor_upper: RankValue | None = None
    anchor_exponent: int | None = Field(default=None, ge=-308, le=306, strict=True)
    # Absence has always meant concentration. Do not add a default field to
    # historical transport/export bytes; only the new log basis needs a marker.
    basis: Literal["concentration", "negative_log_molar"] = Field(
        default="concentration", exclude_if=lambda value: value == "concentration"
    )

    @classmethod
    def from_potency(
        cls, scale: PotencyScale, *, direction: RankDirection | None = None
    ) -> ActivityStrengthScale:
        return cls(
            kind="numeric",
            direction=direction
            or ("higher" if scale.basis == "negative_log_molar" else "lower"),
            rule="tenth_decade",
            method="tenth_decade",
            status=scale.status,
            boundary_inclusive=False,
            population=scale.population,
            anchor_rank=10,
            anchor_exponent=scale.anchor_exponent,
            basis=scale.basis,
            eligible=scale.eligible,
            excluded=scale.excluded,
            distinct=scale.distinct,
            anchor_lower=float(scale.anchor_lower)
            if scale.anchor_lower is not None
            else None,
            anchor_upper=float(scale.anchor_upper)
            if scale.anchor_upper is not None
            else None,
            strong_boundary=float(scale.strong_boundary)
            if scale.strong_boundary is not None
            else None,
            medium_boundary=float(scale.medium_boundary)
            if scale.medium_boundary is not None
            else None,
        )

    @model_validator(mode="after")
    def check_bounds(self) -> ActivityStrengthScale:
        if self.distinct > self.eligible or (self.eligible and not self.distinct):
            raise ValueError("Distinct values exceed eligible observations")
        if self.method == "tenth_decade":
            if (
                self.kind != "numeric"
                or self.boundary_inclusive
                or self.anchor_rank != 10
                or self.population is None
                or (
                    self.status != "unsupported"
                    and self.direction
                    != ("higher" if self.basis == "negative_log_molar" else "lower")
                )
            ):
                raise ValueError(
                    "Tenth-decade metadata must declare its complete positive-concentration population"
                )
            if self.status == "ready":
                if (
                    self.population < 10
                    or self.anchor_exponent is None
                    or self.anchor_lower is None
                    or self.anchor_upper is None
                    or self.anchor_lower > self.anchor_upper
                    or (self.basis == "concentration" and self.anchor_lower <= 0)
                ):
                    raise ValueError(
                        "Available tenth-decade anchor requires its bounded tenth measurement"
                    )
            elif (
                self.anchor_lower is not None
                or self.anchor_upper is not None
                or self.anchor_exponent is not None
            ):
                raise ValueError(
                    "Unavailable tenth-decade anchor cannot carry a guessed measurement"
                )
        elif (
            self.status != "ready"
            or self.anchor_rank is not None
            or self.anchor_lower is not None
            or self.anchor_upper is not None
            or self.anchor_exponent is not None
            or self.population is not None
            or not self.boundary_inclusive
            or self.basis != "concentration"
        ):
            raise ValueError(
                "Legacy grade metadata cannot masquerade as tenth-decade potency"
            )
        if self.direction == "unknown" or not self.eligible or self.status != "ready":
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
        if self.method == "tenth_decade" and self.status == "ready":
            from decimal import Decimal

            if self.basis == "negative_log_molar":
                expected = (-self.anchor_exponent - 1, -self.anchor_exponent - 2)
            else:
                expected = (
                    Decimal(1).scaleb(self.anchor_exponent + 1),
                    Decimal(1).scaleb(self.anchor_exponent + 2),
                )
            if (
                Decimal(str(self.strong_boundary)) != expected[0]
                or Decimal(str(self.medium_boundary)) != expected[1]
            ):
                raise ValueError(
                    "Tenth-decade cutoffs must represent the next two concentration decades"
                )
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
