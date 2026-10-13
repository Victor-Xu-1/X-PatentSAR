"""One context/repeat/value gate shared by ranking and descriptive arithmetic."""

from typing import Any

from .contexts import compare_context, select_observations
from .errors import SARInputError
from .measurements import parse_measurement, scalar_difference
from .values import MISSING, Value, grade_ranks


def empty_comparison() -> dict[str, Any]:
    return {
        "comparison": "indeterminate",
        "reference_values": [],
        "candidate_values": [],
        "fold_change": None,
        "evidence_basis": "insufficient",
        "reasons": [],
    }


def comparable_observations(
    reference_obs: list[dict[str, Any]],
    candidate_obs: list[dict[str, Any]],
    metric_id: str,
    grade_order: list[str],
    confirm_context: bool,
    *,
    inline_units: bool = True,
) -> tuple[dict[str, Any], tuple[Value, Value] | None]:
    """Retain every source reading; never choose a best repeat or infer direction."""
    result = empty_comparison()
    try:
        if (
            not isinstance(metric_id, str)
            or not metric_id
            or len(metric_id) > 200
            or type(confirm_context) is not bool
            or type(inline_units) is not bool
        ):
            raise SARInputError("invalid_statistics_input")
        ranks = grade_ranks(grade_order)
        left = select_observations(reference_obs, metric_id)
        right = select_observations(candidate_obs, metric_id)
        result["reference_values"] = [o["value"] for o in left]
        result["candidate_values"] = [o["value"] for o in right]
        if not left or not right:
            result.update(comparison="missing", reasons=["measurement_missing"])
            return result, None
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
            return result, None
        reference = [
            parse_measurement(
                o["value"], ranks, o.get("unit"), inline_units=inline_units
            )
            for o in left
        ]
        candidate = [
            parse_measurement(
                o["value"], ranks, o.get("unit"), inline_units=inline_units
            )
            for o in right
        ]
        if all(value.kind == "missing" for value in reference) or all(
            value.kind == "missing" for value in candidate
        ):
            result.update(
                comparison="missing", reasons=reasons + ["measurement_missing"]
            )
            return result, None
        if any(value.kind == "missing" for value in reference + candidate):
            result["reasons"] = reasons + ["partial_missing_measurements"]
            return result, None
        if len(reference) > 1 or len(candidate) > 1:
            reasons.append("multiple_measurements")
            if len(set(reference)) > 1 or len(set(candidate)) > 1:
                result["reasons"] = reasons + ["conflicting_measurements"]
                return result, None
            reasons.append("repeated_measurements")
        if basis != "insufficient":
            return result, (reference[0], candidate[0])
    except SARInputError as exc:
        result.update(
            comparison="indeterminate",
            evidence_basis="insufficient",
            reasons=[exc.code],
        )
    return result, None


def recorded_difference(
    reference_obs: list[dict[str, Any]],
    candidate_obs: list[dict[str, Any]],
    metric_id: str,
) -> dict[str, Any]:
    """Descriptive arithmetic only; no ranking direction or inherited confirmation.

    Supporting endpoints were not selected for the study's scientific policy.
    Only their complete recorded conditions can authorize a scalar subtraction.
    """
    assessment, values = comparable_observations(
        reference_obs, candidate_obs, metric_id, [], False
    )
    if values is None:
        return {"status": assessment["comparison"], "value": None}
    if any(value.kind != "scalar" for value in values):
        return {"status": "not_scalar", "value": None}
    value = scalar_difference(*values)
    return {
        "status": "comparable" if value is not None else "not_representable",
        "value": value,
    }
