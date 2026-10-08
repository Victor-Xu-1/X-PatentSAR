"""Conservative recorded-context comparison, without averaging or grade math."""

from __future__ import annotations

import math
from decimal import Context, localcontext
from typing import Any

from .contexts import compare_context, select_observations
from .errors import SARInputError
from .values import MISSING, Value, compare_values, grade_ranks, parse_value


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
) -> dict[str, Any]:
    """Compare only this metric, retaining every raw value in original order.

    grade_order is strongest-first regardless of numeric direction. Different
    repeat readings are explicit conflicts, not averages or a best-only choice.
    fold_change is an improvement-oriented ratio of exact positive raw scalars:
    reference/candidate for lower, candidate/reference for higher. It is not an
    inferred potency ratio, log-scale inversion or fold from a grade/interval.
    """
    result: dict[str, Any] = {
        "comparison": "indeterminate",
        "reference_values": [],
        "candidate_values": [],
        "fold_change": None,
        "evidence_basis": "insufficient",
        "reasons": [],
    }
    try:
        if (
            not isinstance(metric_id, str)
            or not metric_id
            or len(metric_id) > 200
            or not isinstance(direction, str)
            or direction not in {"lower", "higher"}
            or type(confirm_context) is not bool
        ):
            raise SARInputError("invalid_statistics_input")
        ranks = grade_ranks(grade_order)
        left = select_observations(reference_obs, metric_id)
        right = select_observations(candidate_obs, metric_id)
        result["reference_values"] = [o["value"] for o in left]
        result["candidate_values"] = [o["value"] for o in right]
        if not left or not right:
            result.update(comparison="missing", reasons=["measurement_missing"])
            return result
        # Conflicting recorded facts take precedence even when a raw reading
        # cannot be interpreted. Confirmation never bypasses that conflict.
        ordinal = all(
            o["value"].strip() in ranks or o["value"].strip().casefold() in MISSING
            for o in left + right
        )
        basis, reasons, conflict = compare_context(
            left + right, ordinal=ordinal, confirmed=confirm_context
        )
        result.update(evidence_basis=basis, reasons=reasons)
        if conflict:
            result["comparison"] = "context_mismatch"
            return result
        reference = [parse_value(o["value"], ranks) for o in left]
        candidate = [parse_value(o["value"], ranks) for o in right]
        if all(value.kind == "missing" for value in reference) or all(
            value.kind == "missing" for value in candidate
        ):
            result.update(
                comparison="missing", reasons=reasons + ["measurement_missing"]
            )
            return result
        if any(value.kind == "missing" for value in reference + candidate):
            result["reasons"] = reasons + ["partial_missing_measurements"]
            return result
        if len(reference) > 1 or len(candidate) > 1:
            reasons.append("multiple_measurements")
            if len(set(reference)) > 1 or len(set(candidate)) > 1:
                result["reasons"] = reasons + ["conflicting_measurements"]
                return result
            reasons.append("repeated_measurements")
        if basis == "insufficient":
            return result
        comparison, reason = compare_values(
            reference[0], candidate[0], direction, ranks
        )
        if reason:
            reasons.append(reason)
        result.update(comparison=comparison, reasons=reasons)
        if comparison in {"better", "worse", "equal"}:
            fold, reason = _fold(reference[0], candidate[0], direction)
            result["fold_change"] = fold
            if reason:
                reasons.append(reason)
    except SARInputError as exc:
        result.update(
            comparison="indeterminate",
            fold_change=None,
            evidence_basis="insufficient",
            reasons=[exc.code],
        )
    return result
