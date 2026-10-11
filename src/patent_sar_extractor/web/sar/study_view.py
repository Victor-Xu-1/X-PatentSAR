"""Source-bound current tenth-dose presentation over immutable study archives."""

from collections import Counter

from ...core.sar.study_contexts import context_catalog
from ...core.sar.study_distributions import DistributionContext
from ...workers.study_candidates import collect_activities
from ...workers.study_strength import resolve_strength
from ..errors import WebError
from .source_scope import source_exclusion
from .study_models import (
    StudyContext,
    StudyDistribution,
    StudyReport,
    StudyResultPolicy,
)
from .study_view_groups import current_groups


def current_report(packet: dict, captured: StudyReport, pairs: list[dict]):
    excluded = Counter()
    sources = []
    for row in packet["molecules"]:
        reason = source_exclusion(
            row["label"], row.get("source_compound_id"), row.get("issues", [])
        )
        if reason:
            excluded[reason] += 1
        else:
            sources.append(row)
    ids = {row["id"] for row in sources}
    if not ids:
        raise WebError(
            422,
            "sar_numbered_pool_empty",
            "No identified final compounds are available for SAR.",
        )
    policies = [item.model_dump() for item in captured.policies]
    for policy in policies:
        if not policy["grade_order"]:
            policy.update(
                strength_method="tenth_decade",
                strong_threshold=None,
                threshold_inclusive=False,
            )
            policy.pop("strength_scale", None)
    observations, assessments = collect_activities(
        sources,
        policies,
        packet["request"].get("confirm_context", False),
        [item.model_dump() for item in captured.context_declarations],
    )
    catalog = {
        item["id"]: item
        for item in context_catalog(sources, packet["dataset"]["metrics"])
    }
    contexts = [
        StudyContext.model_validate(
            catalog.get(
                item.id,
                {
                    **item.model_dump(),
                    "molecule_count": 0,
                    "observation_count": 0,
                    "distinct_value_count": 0,
                    "value_samples": [],
                },
            )
        )
        for item in captured.contexts
    ]
    policies = resolve_strength(
        policies, [item.model_dump() for item in contexts], observations, assessments
    )
    domains = {
        policy["context_id"]: DistributionContext(
            observations[policy["context_id"]],
            policy,
            assessments[policy["context_id"]],
        )
        for policy in policies
    }
    primary = policies[0]["context_id"]

    rows = [
        row.model_copy(
            update={
                "strong": assessments[primary][row.molecule_id]["strong"],
                "activity_bands": {
                    policy["context_id"]: assessments[policy["context_id"]][
                        row.molecule_id
                    ]["band"]
                    for policy in policies
                },
            }
        )
        for row in captured.rows
        if row.molecule_id in ids
    ]
    by_id = {row.molecule_id: row for row in rows}
    if set(by_id) != ids:
        raise WebError(
            409,
            "sar_report_scope",
            "Captured rows differ from the identified source pool.",
        )
    scaffolds, regions = current_groups(
        captured, ids, domains[primary], assessments[primary], pairs
    )
    current = captured.model_copy(
        update={
            "counting_contract": "unique-molecules-v2",
            "molecule_count": len(sources),
            "eligible_count": sum(row["eligible"] for row in sources),
            "observation_count": sum(len(row["observations"]) for row in sources),
            "contexts": contexts,
            "policies": [StudyResultPolicy.model_validate(item) for item in policies],
            "distributions": [
                StudyDistribution.model_validate(
                    domains[policy["context_id"]].for_members(list(ids))
                )
                for policy in policies
            ],
            "scaffolds": scaffolds,
            "regions": regions,
            "rows": rows,
            "candidates": [
                by_id[row.molecule_id]
                for row in captured.candidates
                if row.molecule_id in by_id
            ],
            "strict_pair_count": len(regions) * (len(ids) - 1),
            "matched_pair_count": sum(item.matched for item in regions),
            "comparable_pair_count": sum(item.comparable for item in regions),
        }
    )
    return current, dict(excluded)
