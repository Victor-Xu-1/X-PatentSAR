"""Resolve one full-context potency scale before any groups, pages or candidates."""

from dataclasses import replace

from patent_sar_extractor.core.potency_bands import PotencyPool, concentration_unit
from patent_sar_extractor.core.sar.measurements import parse_measurement
from patent_sar_extractor.core.sar.study_statistics import strength_band
from patent_sar_extractor.core.sar.values import Value, grade_ranks
from patent_sar_extractor.web.activity_rank_models import ActivityStrengthScale
from patent_sar_extractor.web.indicator_conventions import numeric_direction


def resolve_strength(
    policies,
    contexts,
    observations,
    assessments,
    *,
    inline_units=True,
    log_potency=True,
):
    by_id = {item["id"]: item for item in contexts}
    result = []
    for original in policies:
        policy = dict(original)
        identifier = policy["context_id"]
        if policy.get("grade_order"):
            policy["strength_method"] = "source"
        if policy.get("strength_method", "source") == "tenth_decade":
            pool = PotencyPool(limit=25_000)
            for source_id, records in observations[identifier].items():
                state = assessments[identifier][source_id]
                for observation in records:
                    raw = observation["value"]
                    # Unverified conditions cannot silently contribute a precise
                    # anchor. The unknown bound may or may not affect its decade.
                    if (
                        state["evidence_basis"] == "insufficient"
                        or state["status"] == "context_mismatch"
                    ):
                        raw = "unsupported" if state["status"] != "missing" else ""
                    try:
                        value = parse_measurement(
                            raw, {}, observation.get("unit"), inline_units=inline_units
                        )
                    except ValueError:
                        value = Value("unsupported")
                    pool.observe_value(source_id, value)
            context = by_id[identifier]
            logarithmic = (
                log_potency
                and policy["direction"] == "higher"
                and numeric_direction(
                    context.get("name", ""),
                    context["unit"],
                    context.get("context", {}).get("assay"),
                )[1]
                == "log_potency"
            )
            scale = pool.scale(
                basis="negative_log_molar" if logarithmic else "concentration"
            )
            if not logarithmic and (
                policy["direction"] != "lower"
                or not concentration_unit(by_id[identifier]["unit"])
            ):
                scale = replace(
                    scale,
                    status="unsupported",
                    anchor_lower=None,
                    anchor_upper=None,
                    strong_boundary=None,
                    medium_boundary=None,
                    anchor_exponent=None,
                )
            policy.update(
                strength_scale=ActivityStrengthScale.from_potency(
                    scale, direction=policy["direction"]
                ).model_dump(),
                strong_threshold=None,
                threshold_inclusive=False,
            )
        ranks = grade_ranks(policy.get("grade_order", []))
        for state in assessments[identifier].values():
            state["band"] = (
                strength_band(state["value"], policy, ranks)
                if state["value"] is not None
                else "unclassified"
            )
            state["strong"] = state["band"] == "strong"
        result.append(policy)
    return result
