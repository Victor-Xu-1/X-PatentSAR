"""Exact-context study distributions, repeat evidence and proved strength."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

from .contexts import compare_context, select_observations
from .errors import SARInputError
from .values import Value, grade_ranks, parse_value


def proven_strong(value: Value, policy: dict, ranks: dict[str, int]) -> bool | None:
    if value.kind == "ordinal":
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
) -> dict:
    """Every raw observation counts once; each bin counts distinct members once."""
    ranks = grade_ranks(policy.get("grade_order", []))
    entries = []
    scalars: list[Decimal] = []
    for identifier in members:
        for observation in observations[identifier]:
            raw = observation["value"]
            try:
                value = parse_value(raw, ranks)
            except SARInputError:
                value = Value("unsupported")
            entries.append((identifier, value))
            if value.kind == "scalar":
                scalars.append(value.numeric_bounds()[0])
    bins: dict[tuple[str, str], dict] = {}

    def add(label, kind, identifier, strong=False):
        key = kind, label
        bucket = bins.setdefault(
            key,
            {
                "label": label,
                "kind": kind,
                "observations": 0,
                "ids": set(),
                "strong": strong,
            },
        )
        bucket["observations"] += 1
        bucket["ids"].add(identifier)
        bucket["strong"] = bucket["strong"] and strong

    for grade in ranks:
        bins[("ordinal", grade)] = {
            "label": grade,
            "kind": "ordinal",
            "observations": 0,
            "ids": set(),
            "strong": ranks[grade] == 0,
        }
    with localcontext() as context:
        context.prec = 50
        low, high = (
            (min(scalars), max(scalars)) if scalars else (Decimal(0), Decimal(0))
        )
        width = (high - low) / 8 if scalars and low != high else None
        for identifier, value in entries:
            if value.kind == "ordinal":
                add(value.grade, "ordinal", identifier, ranks[value.grade] == 0)
            elif value.kind == "scalar":
                if width is None:
                    label = str(low)
                else:
                    index = min(7, int((value.low - low) / width))
                    label = f"[{low + width * index},{low + width * (index + 1)}{']' if index == 7 else ')'}"
                add(
                    label,
                    "numeric",
                    identifier,
                    proven_strong(value, policy, ranks) is True,
                )
            elif value.kind == "interval":
                strong = proven_strong(value, policy, ranks) is True
                add(
                    "proved strong bound" if strong else "interval / censored",
                    "interval",
                    identifier,
                    strong,
                )
            else:
                add(value.kind, value.kind, identifier)
    missing = sum(assessments[item]["status"] == "missing" for item in members)
    return {
        "context_id": policy["context_id"],
        "bins": [
            {
                "label": bucket["label"],
                "kind": bucket["kind"],
                "observations": bucket["observations"],
                "molecules": len(bucket["ids"]),
                "strong": bucket["strong"],
            }
            for bucket in bins.values()
        ],
        "observed_molecules": len(members) - missing,
        "observations": len(entries),
        "missing_molecules": missing,
        "unresolved_molecules": sum(
            assessments[item]["status"] in {"indeterminate", "context_mismatch"}
            for item in members
        ),
        "strong_molecules": sum(assessments[item]["strong"] for item in members),
    }
