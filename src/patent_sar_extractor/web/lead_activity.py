"""Exact-context project percentiles; repeats contribute their worst reading."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from .activity_columns import (
    MAX_ACTIVITY_COLUMNS,
    ActivityContext,
    activity_column_id,
    activity_context,
)
from .activity_rank_models import RankDirection, RankKind
from .activity_rank_values import rank_direction, rank_value
from .errors import WebError
from .models import ActivityColumn, Compound

MAX_LEAD_OBSERVATIONS = 100_000
_COUNTER = re.compile(
    r"\b(?:inactive|inactivity|toxic(?:ity)?|cytotox(?:ic(?:ity)?)?|safety|counter(?:screen|assay)?|"
    r"selectivity|normal\s+cell|healthy\s+cell|off[- ]target|negative\s+control|vehicle\s+control|hERG|AMES|DILI|ClinTox)\b|"
    r"\b(?:no|not|without)\s+(?:activity|inhibition|degradation|active)\b",
    re.IGNORECASE,
)
_BIOLOGICAL = re.compile(
    r"prolif(?:eration|erative)?|degrad(?:ation)?|inhibit(?:ion)?|binding|"
    r"anti[- ]prolif|activation",
    re.IGNORECASE,
)
_YMIN = re.compile(r"\by[ _-]?min\b", re.IGNORECASE)
_YMIN_CONTEXT = re.compile(r"prolif|degrad", re.IGNORECASE)
_CONCENTRATION = frozenset({"m", "mm", "um", "nm", "pm", "fm"})
_DIMENSIONLESS = frozenset({"", "1", "-", "unitless", "dimensionless", "ratio"})


def check_cancel(cancel: Callable[[], bool] | None) -> None:
    if cancel is not None and cancel():
        raise WebError(409, "lead_cancelled", "Lead prioritization was cancelled.")


def _direction(context: ActivityContext, kind: RankKind) -> tuple[RankDirection, str]:
    name, unit, target, assay = context
    description = " ".join(value or "" for value in (name, target, assay))
    normalized_unit = (
        (unit or "").strip().casefold().replace("μ", "u").replace("µ", "u")
    )
    if _COUNTER.search(description):
        return "unknown", "counter_or_negative_context"
    if kind == "numeric" and _YMIN.search(name):
        if _YMIN_CONTEXT.search(description) and normalized_unit in {"%", "percent"}:
            return "lower", "ymin_remaining"
        return "unknown", "unknown_ymin_context_or_unit"
    direction, rule = rank_direction(name, unit, assay, kind)
    if rule == "potency" and normalized_unit not in _CONCENTRATION:
        return "unknown", "unknown_concentration_unit"
    if (
        rule in {"log_potency", "htrf_competition"}
        and normalized_unit not in _DIMENSIONLESS
    ):
        return "unknown", "unexpected_dimensionless_unit"
    if kind in {"plus", "letter"} and normalized_unit not in _DIMENSIONLESS:
        return "unknown", "unexpected_grade_unit"
    if kind == "plus" and not (
        _BIOLOGICAL.search(description)
        or ("htrf" in name.casefold() and (assay or "").casefold() == "htrf")
    ):
        return "unknown", "unknown_grade_context"
    return direction, rule


@dataclass(slots=True)
class _Reading:
    worst: float | None = None
    invalid: bool = False
    observations: int = 0
    sourced: int = 0


@dataclass(slots=True)
class _Column:
    context: ActivityContext
    readings: dict[str, _Reading] = field(default_factory=dict)
    kinds: set[RankKind] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class ActivityEvidence:
    potency: float = 0.0
    coverage: float = 0.0
    provenance: float = 0.0
    ranked_columns: int = 0
    total_columns: int = 0
    excluded_columns: int = 0


def _observe(
    column: _Column, compound_id: str, value: object, page: int | None
) -> None:
    reading = column.readings.setdefault(compound_id, _Reading())
    reading.observations += 1
    reading.sourced += int(page is not None and 1 <= page <= 20_000)
    parsed = rank_value(value)
    if parsed is None:
        reading.invalid = True
        return
    kind, number = parsed
    # A known scalar of another type still proves mixed column semantics even
    # when that type/unit combination is not rankable. Do not silently retain
    # the numeric subset of a column that also contains ordinal observations.
    column.kinds.add(kind)
    direction, rule = _direction(column.context, kind)
    if direction == "unknown" or (rule == "potency" and number <= 0):
        reading.invalid = True
        return
    if (kind == "letter" and not 0 <= number <= 3) or (
        rule in {"effect_percent", "remaining_percent"} and not 0 <= number <= 100
    ):
        reading.invalid = True
        return
    # Negative measured Ymin is retained and ranked, never clamped to zero.
    if reading.worst is None:
        reading.worst = number
    else:
        reading.worst = (
            max(reading.worst, number)
            if direction == "lower"
            else min(reading.worst, number)
        )


def _percentiles(values: Counter[float], *, higher: bool) -> dict[float, float]:
    total, worse = values.total(), 0
    result = {}
    for value in sorted(values, reverse=not higher):
        ties = values[value]
        result[value] = (worse + (ties - 1) / 2) / (total - 1) if total > 1 else 0.5
        worse += ties
    return result


def activity_evidence(
    compounds: list[Compound],
    activity_columns: list[ActivityColumn],
    cancel: Callable[[], bool] | None = None,
) -> dict[str, ActivityEvidence]:
    """Full-project input only: no page extrema, cross-unit merge or imputation."""
    if len(activity_columns) > MAX_ACTIVITY_COLUMNS:
        raise WebError(422, "lead_limit", "Lead activity columns exceed 1000 contexts.")
    columns: dict[ActivityContext, _Column] = {}
    for column in activity_columns:
        check_cancel(cancel)
        context = column.name, column.unit, column.target, column.assay
        if (
            context in columns
            or any(value is not None and len(value) > 1000 for value in context)
            or column.id != activity_column_id(context)
        ):
            raise WebError(
                422, "lead_activity_context", "Lead activity catalog is inconsistent."
            )
        columns[context] = _Column(context)
    observations = 0
    for compound in compounds:
        check_cancel(cancel)
        observations += len(compound.activities)
        if observations > MAX_LEAD_OBSERVATIONS:
            raise WebError(
                422, "lead_limit", "Lead observations exceed 100000 readings."
            )
        for activity in compound.activities:
            check_cancel(cancel)
            column = columns.get(activity_context(activity))
            if column is None:
                raise WebError(
                    422,
                    "lead_activity_context",
                    "Lead input is missing an observed activity column.",
                )
            _observe(column, compound.id, activity.value, activity.page)
    totals = {compound.id: [0.0, 0.0, 0, 0] for compound in compounds}
    rankable_columns = 0
    for context in sorted(
        columns,
        key=lambda item: tuple((value is not None, value or "") for value in item),
    ):
        check_cancel(cancel)
        column = columns[context]
        if len(column.kinds) != 1:
            for compound_id in column.readings:
                totals[compound_id][3] += 1
            continue
        kind = next(iter(column.kinds))
        direction, _rule = _direction(column.context, kind)
        values = Counter(
            reading.worst
            for reading in column.readings.values()
            if not reading.invalid and reading.worst is not None
        )
        if not values:
            for compound_id in column.readings:
                totals[compound_id][3] += 1
            continue
        rankable_columns += 1
        ranks = _percentiles(values, higher=direction == "higher")
        for compound_id, reading in column.readings.items():
            if reading.invalid or reading.worst is None:
                totals[compound_id][3] += 1
                continue
            aggregate = totals[compound_id]
            aggregate[0] += ranks[reading.worst] * 100
            aggregate[1] += reading.sourced / reading.observations
            aggregate[2] += 1
    return {
        compound_id: ActivityEvidence(
            potency=values[0] / values[2] if values[2] else 0.0,
            coverage=values[2] / rankable_columns if rankable_columns else 0.0,
            provenance=values[1] / values[2] if values[2] else 0.0,
            ranked_columns=int(values[2]),
            total_columns=rankable_columns,
            excluded_columns=int(values[3]),
        )
        for compound_id, values in totals.items()
    }
