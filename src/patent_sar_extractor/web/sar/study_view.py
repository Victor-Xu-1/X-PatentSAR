"""Source-bound current views over the same complete immutable study archives."""

from .study_activity_view import prepare_activity
from .study_models import StudyReport
from .study_projection_models import CurrentStudyDistribution, CurrentStudyReport
from .study_view_groups import current_groups, source_groups
from .study_view_models import CurrentRecordView


def current_records(packet: dict, captured: StudyReport, pairs: list[dict]):
    activity = prepare_activity(packet, captured)
    scope = source_groups(captured, activity.ids, pairs)
    return (
        CurrentRecordView(
            inline_units=activity.inline_units,
            declared_units=activity.declared_units,
            molecule_count=len(activity.sources),
            molecule_ids=activity.ids,
            policies=activity.policies,
            contexts=activity.contexts,
            context_declarations=captured.context_declarations,
            rows=activity.rows,
            scaffolds=scope.scaffolds,
            regions=scope.regions,
        ),
        activity.excluded,
    )


def current_report(packet: dict, captured: StudyReport, pairs: list[dict]):
    activity = prepare_activity(packet, captured)
    primary = activity.policies[0].context_id
    scaffolds, regions = current_groups(
        captured,
        activity.ids,
        activity.domains[primary],
        activity.assessments[primary],
        pairs,
    )
    by_id = {row.molecule_id: row for row in activity.rows}
    current = CurrentStudyReport.model_validate(
        {
            **captured.__dict__,
            "counting_contract": "unique-molecules-v2",
            "molecule_count": len(activity.sources),
            "eligible_count": sum(row["eligible"] for row in activity.sources),
            "observation_count": sum(
                len(row["observations"]) for row in activity.sources
            ),
            "contexts": activity.contexts,
            "policies": activity.policies,
            "distributions": [
                CurrentStudyDistribution.model_validate(
                    activity.domains[policy.context_id].for_members(list(activity.ids))
                )
                for policy in activity.policies
            ],
            "scaffolds": scaffolds,
            "regions": regions,
            "rows": activity.rows,
            "candidates": [
                by_id[row.molecule_id]
                for row in captured.candidates
                if row.molecule_id in by_id
            ],
            "strict_pair_count": sum(
                len(summary.comparison_pool)
                if summary.comparison_pool is not None
                else len(activity.ids) - 1
                for summary in regions
            ),
            "matched_pair_count": sum(item.matched for item in regions),
            "comparable_pair_count": sum(item.comparable for item in regions),
        }
    )
    return current, activity.excluded
