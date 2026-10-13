"""Conservative recorded-context comparison, without averaging or grade math."""

from __future__ import annotations

import math
from decimal import Context, localcontext
from typing import Any

from .errors import SARInputError
from .observation_pair import comparable_observations, empty_comparison
from .values import Value, compare_values, grade_ranks


def _fold(
    reference: Value, candidate: Value, direction: str
) -> tuple[float | None, str | None]:
    if reference.kind != "scalar" or candidate.kind != "scalar":
        return None, None
    reference_value, _ = reference.numeric_bounds()
    candidate_value, _ = candidate.numeric_bounds()
    if reference_value <= 0 or candidate_value <= 0:
        return None, "fold_requires_positive_scalars"
    with localcontext(Context(prec=50)):
        ratio = (
            reference_value / candidate_value
            if direction == "lower"
            else candidate_value / reference_value
        )
        fold = float(ratio)
    if not math.isfinite(fold) or fold <= 0:
        return None, "fold_out_of_range"
    return fold, None


def compare_observations(
    reference_obs: list[dict[str, Any]],
    candidate_obs: list[dict[str, Any]],
    metric_id: str,
    direction: str,
    grade_order: list[str],
    confirm_context: bool,
    *,
    open_bounds: bool = True,
    inline_units: bool = True,
) -> dict[str, Any]:
    """Rank only after the shared context/repeat/value gate accepts both sides.

    Grades stay strongest-first. Fold is an improvement-oriented raw scalar
    ratio, not log-scale inversion or a manufactured interval/grade fold.
    """
    result = empty_comparison()
    try:
        if (
            not isinstance(direction, str)
            or direction not in {"lower", "higher"}
            or type(open_bounds) is not bool
        ):
            raise SARInputError("invalid_statistics_input")
        result, values = comparable_observations(
            reference_obs,
            candidate_obs,
            metric_id,
            grade_order,
            confirm_context,
            inline_units=inline_units,
        )
        if values is None:
            return result
        reference, candidate = values
        comparison, reason = compare_values(
            reference,
            candidate,
            direction,
            grade_ranks(grade_order),
            open_bounds=open_bounds,
        )
        if reason:
            result["reasons"].append(reason)
        result["comparison"] = comparison
        if comparison in {"better", "worse", "equal"}:
            fold, reason = _fold(reference, candidate, direction)
            result["fold_change"] = fold
            if reason:
                result["reasons"].append(reason)
    except SARInputError as exc:
        result.update(
            comparison="indeterminate",
            fold_change=None,
            evidence_basis="insufficient",
            reasons=[exc.code],
        )
    return result
