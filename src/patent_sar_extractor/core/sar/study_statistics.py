"""Exact-context study distributions, repeat evidence and proved strength."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..potency_bands import classify_potency
from .contexts import compare_context, select_observations
from .errors import SARInputError
from .values import Value, grade_ranks, parse_value


def proven_strong(value: Value, policy: dict, ranks: dict[str, int]) -> bool | None:
    if policy.get("strength_method") == "unclassified":
        return None
    if policy.get("strength_method") == "tenth_decade" and not ranks:
        band = strength_band(value, policy, ranks)
        return None if band == "unclassified" else band == "strong"
    if value.kind == "ordinal":
        if value.grade is None or value.grade not in ranks:
            raise SARInputError("invalid_grade_value")
        return ranks[value.grade] == 0
    if value.kind == "missing" or policy.get("strong_threshold") is None:
        return None
    threshold = Decimal(str(policy["strong_threshold"]))
    inclusive = policy.get("threshold_inclusive", True)
    low, high = value.numeric_bounds()
    if policy["direction"] == "lower":
        return high < threshold or (
            high == threshold and (inclusive or not value.upper_closed)
        )
    return low > threshold or (
        low == threshold and (inclusive or not value.lower_closed)
    )


def strength_band(value: Value | None, policy: dict, ranks: dict[str, int]) -> str:
    if value is None or policy.get("strength_method") == "unclassified":
        return "unclassified"
    if policy.get("strength_method") == "tenth_decade" and not ranks:
        scale = policy.get("strength_scale")
        if not scale or scale["status"] != "ready":
            return "unclassified"
        return classify_potency(
            value,
            Decimal(str(scale["strong_boundary"])),
            Decimal(str(scale["medium_boundary"])),
        )
    known = proven_strong(value, policy, ranks)
    return "unclassified" if known is None else "strong" if known else "weak"


def assess(observations: list[dict], policy: dict, confirmed: bool) -> dict:
    result: dict[str, Any] = {
        "status": "missing",
        "value": None,
        "strong": False,
        "evidence_basis": "insufficient",
        "reasons": [],
        "values": [item["value"] for item in observations],
    }
    if not observations:
        return result
    try:
        ranks = grade_ranks(policy.get("grade_order", []))
        selected = select_observations(observations, observations[0]["metric_id"])
        parsed = [parse_value(item["value"], ranks) for item in selected]
        ordinal = all(item.kind in {"ordinal", "missing"} for item in parsed)
        basis, reasons, conflict = compare_context(
            selected, ordinal=ordinal, confirmed=confirmed
        )
        result.update(evidence_basis=basis, reasons=reasons)
        if conflict:
            result["status"] = "context_mismatch"
        elif all(item.kind == "missing" for item in parsed):
            result["status"] = "missing"
        elif any(item.kind == "missing" for item in parsed):
            result.update(
                status="indeterminate",
                reasons=reasons + ["partial_missing_measurements"],
            )
        elif len(set(parsed)) > 1:
            result.update(
                status="indeterminate", reasons=reasons + ["conflicting_measurements"]
            )
        elif basis == "insufficient":
            result["status"] = "indeterminate"
        else:
            result.update(
                status=parsed[0].kind,
                value=parsed[0],
                strong=proven_strong(parsed[0], policy, ranks) is True,
            )
            if len(parsed) > 1:
                result["reasons"] = reasons + ["repeated_measurements"]
            if parsed[0].kind == "interval":
                result["reasons"].append(
                    "interval_priority_requires_strict_bound_separation"
                )
    except SARInputError as error:
        result.update(status="indeterminate", reasons=[error.code])
    return result


def distribution(
    members: list[str],
    observations: dict[str, list[dict]],
    policy: dict,
    assessments: dict[str, dict],
    *,
    prepared=None,
) -> dict:
    """One authority; workers reuse a prepared whole-context chart domain."""
    from .study_distributions import DistributionContext

    if prepared is None:
        prepared = DistributionContext(observations, policy, assessments)
    elif not prepared.matches(observations, policy, assessments):
        raise SARInputError("study_distribution_context")
    return prepared.for_members(members)
