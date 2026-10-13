"""One bounded, repeat-aware tenth-potency decade rule, with exact boundaries.

Source units and observations are never rewritten. Positive concentrations and
defined negative-log molar potency share one underlying concentration-decade rule.
Ordered grade labels and effect percentages are not doses.
The tenth order statistic is bounded using every measured source identity; an
uncertain reading cannot be silently dropped to improve the anchor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .potency_axes import UNKNOWN, PotencyBasis, decade_bounds, potency_range
from .sar.values import Value, parse_value

Tier = Literal["strong", "medium", "weak", "unclassified"]
Status = Literal["ready", "insufficient", "ambiguous", "limit", "unsupported"]


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
    return potency_range(value, "concentration")


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
    basis: PotencyBasis = "concentration"
    anchor_exponent: int | None = None

    def band(self, value: Value) -> Tier:
        if self.status != "ready":
            return "unclassified"
        return classify_potency(
            value, self.strong_boundary, self.medium_boundary, basis=self.basis
        )


def classify_potency(
    value: Value,
    strong: Decimal | None,
    medium: Decimal | None,
    *,
    basis: PotencyBasis = "concentration",
) -> Tier:
    positive = potency_range(value, basis)
    if positive is None or strong is None or medium is None:
        return "unclassified"
    low, high = positive.numeric_bounds()
    if basis == "negative_log_molar":
        strong, medium = strong.copy_negate(), medium.copy_negate()
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
        self.nonpositive: set[str] = set()

    def observe(self, identity: str, raw: object) -> None:
        if self.overflow:
            return
        try:
            value = parse_value(str(raw) if raw is not None else "", {})
        except ValueError:
            value = Value("unsupported")
        self.observe_value(identity, value)

    def observe_value(self, identity: str, value: Value) -> None:
        """Consume an already interpreted reading through the same pool rules."""
        if self.overflow:
            return
        if identity not in self.readings and len(self.readings) >= self.limit:
            self.overflow = True
            self.readings.clear()
            self.uncertain.clear()
            self.nonpositive.clear()
            return
        if value.kind != "missing":
            if value.kind not in {"scalar", "interval"}:
                self.uncertain.add(identity)
                value = UNKNOWN
            elif positive_range(value) is None:
                self.nonpositive.add(identity)
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

    def scale(self, *, basis: PotencyBasis = "concentration") -> PotencyScale:
        if basis not in {"concentration", "negative_log_molar"}:
            raise ValueError("unsupported_potency_basis")
        normalized = {
            identity: (
                None
                if basis == "concentration" and identity in self.nonpositive
                else potency_range(value, basis)
            )
            for identity, value in self.readings.items()
            if value.kind != "missing"
        }
        unknown = potency_range(UNKNOWN, basis)
        samples = [
            value if value is not None else unknown for value in normalized.values()
        ]
        valid = [
            value
            for identity, value in normalized.items()
            if identity not in self.uncertain and value is not None
        ]
        counts = {
            "population": len(samples),
            "eligible": len(valid),
            "excluded": len(self.readings) - len(valid),
            "distinct": len(set(valid)),
            "basis": basis,
        }
        if self.overflow:
            return PotencyScale("limit", **counts)
        if len(samples) < 10:
            return PotencyScale("insufficient", **counts)
        low, _ = sorted((x.low, not x.lower_closed) for x in samples)[9]
        high, high_closed = sorted((x.high, x.upper_closed) for x in samples)[9]
        exponent = decade_bounds(low, high, high_closed, basis)
        if exponent is None:
            return PotencyScale("ambiguous", **counts)
        if basis == "negative_log_molar":
            low, high = high.copy_negate(), low.copy_negate()
            strong, medium = Decimal(-exponent - 1), Decimal(-exponent - 2)
        else:
            strong = Decimal(1).scaleb(exponent + 1)
            medium = Decimal(1).scaleb(exponent + 2)
        if any(
            not math.isfinite(float(x)) or (basis == "concentration" and float(x) <= 0)
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
            anchor_exponent=exponent,
        )
