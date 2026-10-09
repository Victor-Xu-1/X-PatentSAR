"""One bounded, repeat-aware tenth-potency decade rule, with exact boundaries.

Source units and observations are never rewritten. Lower-is-stronger, positive
concentrations only: ordered grade labels and effect percentages are not doses.
The tenth order statistic is bounded using every measured source identity; an
uncertain reading cannot be silently dropped to improve the anchor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .sar.values import Value, parse_value

Tier = Literal["strong", "medium", "weak", "unclassified"]
Status = Literal["ready", "insufficient", "ambiguous", "limit", "unsupported"]
ZERO, INFINITY = Decimal(0), Decimal("Infinity")
UNKNOWN = Value("interval", ZERO, INFINITY, False, False)


def concentration_unit(unit: str | None) -> bool:
    return (unit or "").strip().casefold().replace("µ", "u").replace("μ", "u") in {
        "m",
        "mm",
        "um",
        "nm",
        "pm",
        "fm",
    }


def positive_range(value: Value) -> Value | None:
    if value.kind not in {"scalar", "interval"}:
        return None
    low, high = value.numeric_bounds()
    if high <= 0 or (value.kind == "scalar" and low <= 0):
        return None
    return Value(
        value.kind,
        max(ZERO, low),
        high,
        value.lower_closed if low > 0 else False,
        value.upper_closed,
    )


@dataclass(frozen=True, slots=True)
class PotencyScale:
    status: Status
    population: int
    eligible: int
    excluded: int
    distinct: int
    anchor_lower: Decimal | None = None
    anchor_upper: Decimal | None = None
    strong_boundary: Decimal | None = None
    medium_boundary: Decimal | None = None

    def band(self, value: Value) -> Tier:
        if self.status != "ready":
            return "unclassified"
        return classify_potency(value, self.strong_boundary, self.medium_boundary)


def classify_potency(
    value: Value, strong: Decimal | None, medium: Decimal | None
) -> Tier:
    positive = positive_range(value)
    if positive is None or strong is None or medium is None:
        return "unclassified"
    low, high = positive.numeric_bounds()
    if high < strong or (high == strong and not positive.upper_closed):
        return "strong"
    if low >= strong and (
        high < medium or (high == medium and not positive.upper_closed)
    ):
        return "medium"
    if low >= medium:
        return "weak"
    return "unclassified"


class PotencyPool:
    """O(N) storage and O(N log N) once per complete context, never per page."""

    def __init__(self, *, limit: int = 50_000):
        self.limit, self.overflow = limit, False
        self.readings: dict[str, Value] = {}
        self.uncertain: set[str] = set()

    def observe(self, identity: str, raw: object) -> None:
        if self.overflow:
            return
        if identity not in self.readings and len(self.readings) >= self.limit:
            self.overflow = True
            self.readings.clear()
            self.uncertain.clear()
            return
        try:
            value = parse_value(str(raw) if raw is not None else "", {})
        except ValueError:
            value = UNKNOWN
            self.uncertain.add(identity)
        if value.kind != "missing":
            positive = positive_range(value)
            if positive is None:
                self.uncertain.add(identity)
                value = UNKNOWN
            else:
                value = positive
        old = self.readings.get(identity)
        if old is None or old == value:
            self.readings[identity] = value
        elif old.kind == "missing" or value.kind == "missing":
            self.readings[identity] = UNKNOWN
            self.uncertain.add(identity)
        else:
            low, high = min(old.low, value.low), max(old.high, value.high)
            self.readings[identity] = Value(
                "interval",
                low,
                high,
                any(x.low == low and x.lower_closed for x in (old, value)),
                any(x.high == high and x.upper_closed for x in (old, value)),
            )

    def scale(self) -> PotencyScale:
        samples = [value for value in self.readings.values() if value.kind != "missing"]
        valid = [
            value
            for identity, value in self.readings.items()
            if identity not in self.uncertain and value.kind != "missing"
        ]
        counts = {
            "population": len(samples),
            "eligible": len(valid),
            "excluded": len(self.readings) - len(valid),
            "distinct": len(set(valid)),
        }
        if self.overflow:
            return PotencyScale("limit", **counts)
        if len(samples) < 10:
            return PotencyScale("insufficient", **counts)
        low, _ = sorted((x.low, not x.lower_closed) for x in samples)[9]
        high, high_closed = sorted((x.high, x.upper_closed) for x in samples)[9]
        if low <= 0 or not high.is_finite():
            return PotencyScale("ambiguous", **counts)
        low_decade, high_decade = low.adjusted(), high.adjusted()
        if not high_closed and high == Decimal(1).scaleb(high_decade):
            high_decade -= 1
        strong = Decimal(1).scaleb(low_decade + 1)
        medium = Decimal(1).scaleb(low_decade + 2)
        if low_decade != high_decade or any(
            not math.isfinite(float(x)) or float(x) <= 0
            for x in (low, high, strong, medium)
        ):
            return PotencyScale("ambiguous", **counts)
        return PotencyScale(
            "ready",
            **counts,
            anchor_lower=low,
            anchor_upper=high,
            strong_boundary=strong,
            medium_boundary=medium,
        )
