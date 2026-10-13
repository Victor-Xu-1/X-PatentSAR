"""One complete source/context/row preparation for all current study readers."""

from collections import Counter
from dataclasses import dataclass

from ...core.sar.study_contexts import context_catalog
from ...core.sar.study_distributions import DistributionContext
from ...workers.study_candidates import collect_activities
from ...workers.study_strength import resolve_strength
from ..errors import WebError
from .source_scope import source_exclusion
from .study_models import StudyContext, StudyReport, StudyResultPolicy, StudyRow


@dataclass(frozen=True)
class ActivityView:
    sources: list[dict]
    ids: set[str]
    contexts: list[StudyContext]
    policies: list[StudyResultPolicy]
    domains: dict[str, DistributionContext]
    assessments: dict
    rows: list[StudyRow]
    excluded: dict[str, int]
    inline_units: bool


def prepare_activity(packet: dict, captured: StudyReport) -> ActivityView:
    if packet.get("schema") not in {2, 3, 4}:
        raise WebError(409, "sar_input_changed", "Unknown study measurement policy.")
    inline_units = packet["schema"] == 4
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
        inline_units=inline_units,
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
        policies,
        [item.model_dump() for item in contexts],
        observations,
        assessments,
        inline_units=inline_units,
    )
    domains = {
        policy["context_id"]: DistributionContext(
            observations[policy["context_id"]],
            policy,
            assessments[policy["context_id"]],
            inline_units=inline_units,
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
    if {row.molecule_id for row in rows} != ids:
        raise WebError(
            409,
            "sar_report_scope",
            "Captured rows differ from the identified source pool.",
        )
    return ActivityView(
        sources=sources,
        ids=ids,
        contexts=contexts,
        policies=[StudyResultPolicy.model_validate(item) for item in policies],
        domains=domains,
        assessments=assessments,
        rows=rows,
        excluded=dict(excluded),
        inline_units=inline_units,
    )
