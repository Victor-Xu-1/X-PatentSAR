"""One whole-project authority: tenth-dose decades or source-only grade ranks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from itertools import accumulate

from ..core.potency_bands import PotencyPool, concentration_unit
from .activity_rank_models import ActivityStrengthScale, RankKind
from .activity_rank_values import rank_direction, rank_value


@dataclass
class RankBudget:
    # Shared by the existing bounded catalog, not a separate dataset or cache.
    remaining: int = 50_000
    remaining_subjects: int = 100_000


def tied_grade_terciles(values: Counter[float], *, higher: bool) -> tuple[float, float]:
    ordered = sorted(values, reverse=higher)
    if len(ordered) < 3:
        # One value: all tied first. Two values: first and last, no invented middle.
        return ordered[0], ordered[0]
    cumulative = list(accumulate(values[value] for value in ordered))
    total = cumulative[-1]
    first = min(
        range(len(ordered) - 2), key=lambda i: (abs(3 * cumulative[i] - total), i)
    )
    second = min(
        range(first + 1, len(ordered) - 1),
        key=lambda i: (abs(3 * cumulative[i] - 2 * total), i),
    )
    return ordered[first], ordered[second]


class RankDistribution:
    def __init__(self, budget: RankBudget) -> None:
        self.budget = budget
        self.values: Counter[float] = Counter()
        self.kind: RankKind = "unknown"
        self.total = 0
        self.reason: str | None = None
        self.pool = PotencyPool()

    def _unavailable(self, reason: str) -> None:
        self.reason = reason
        self.budget.remaining += len(self.values)
        self.values.clear()
        self.kind = "unknown"
        self.budget.remaining_subjects += len(self.pool.readings)
        self.pool.readings.clear()
        self.pool.uncertain.clear()

    def observe(self, value: object, subject: str | None = None) -> None:
        self.total += 1
        if self.reason:
            return
        identity = subject if subject is not None else str(self.total)
        if identity not in self.pool.readings and not self.pool.overflow:
            if self.budget.remaining_subjects <= 0:
                self._unavailable("limit")
                return
            self.budget.remaining_subjects -= 1
        self.pool.observe(identity, value)
        parsed = rank_value(value)
        if parsed is None:
            return
        kind, score = parsed
        if self.kind != "unknown" and kind != self.kind:
            self._unavailable("mixed_types")
            return
        self.kind = kind
        if score not in self.values:
            if self.budget.remaining <= 0:
                self._unavailable("limit")
                return
            self.budget.remaining -= 1
        self.values[score] += 1

    def profile(
        self, name: str, unit: str | None, assay: str | None
    ) -> ActivityStrengthScale:
        kind = self.kind
        if (
            kind == "unknown"
            and not self.reason
            and concentration_unit(unit)
            and rank_direction(name, unit, assay, "numeric")[1] == "potency"
        ):
            kind = "numeric"
        direction, rule = rank_direction(name, unit, assay, kind)
        if kind == "numeric" and not self.reason:
            scale = self.pool.scale()
            if (
                direction != "lower"
                or rule != "potency"
                or not concentration_unit(unit)
            ):
                scale = replace(
                    scale,
                    status="unsupported",
                    anchor_lower=None,
                    anchor_upper=None,
                    strong_boundary=None,
                    medium_boundary=None,
                )
            return ActivityStrengthScale.from_potency(scale, direction=direction)
        if self.reason:
            direction, rule = "unknown", self.reason
        eligible = self.values.total()
        strong, medium = (
            tied_grade_terciles(self.values, higher=direction == "higher")
            if direction != "unknown" and eligible
            else (None, None)
        )
        return ActivityStrengthScale(
            kind=self.kind,
            direction=direction,
            rule=rule,
            eligible=eligible,
            excluded=self.total - eligible,
            distinct=len(self.values),
            strong_boundary=strong,
            medium_boundary=medium,
        )
