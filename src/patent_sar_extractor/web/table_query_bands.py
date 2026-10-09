"""Color selectors consume the same complete-project strength scale as the UI."""

from __future__ import annotations

from typing import Literal

from decimal import Decimal
from ..core.potency_bands import classify_potency
from ..core.sar.values import parse_value

from .activity_rank_models import ActivityStrengthScale
from .activity_rank_values import rank_value
from .models import Compound
from .table_query_values import column_values

Band = Literal["strong", "medium", "none"]
BANDS: tuple[Band, ...] = ("strong", "medium", "none")


def value_band(value: object, scale: ActivityStrengthScale | None) -> Band:
    if scale and scale.method == "tenth_decade":
        if scale.status != "ready":
            return "none"
        try:
            parsed_value = parse_value(str(value) if value is not None else "", {})
        except ValueError:
            return "none"
        tier = classify_potency(
            parsed_value,
            Decimal(str(scale.strong_boundary)),
            Decimal(str(scale.medium_boundary)),
        )
        return tier if tier in {"strong", "medium"} else "none"
    parsed = rank_value(value)
    if (
        parsed is None
        or scale is None
        or parsed[0] != scale.kind
        or scale.direction == "unknown"
        or not scale.eligible
        or scale.status != "ready"
        or scale.strong_boundary is None
        or scale.medium_boundary is None
    ):
        return "none"
    score = parsed[1]
    if scale.direction == "lower":
        if score <= scale.strong_boundary:
            return "strong"
        if score <= scale.medium_boundary:
            return "medium"
    else:
        if score >= scale.strong_boundary:
            return "strong"
        if score >= scale.medium_boundary:
            return "medium"
    return "none"


def row_bands(
    row: Compound, column: str, scale: ActivityStrengthScale | None
) -> list[Band]:
    values = column_values(row, column)
    return [value_band(value, scale) for value in values] if values else ["none"]
