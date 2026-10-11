"""Exact published memberships for table, selected-site and whole-core reads."""

from ..errors import WebError
from .study_view_models import CurrentRecordView


def selected_members(
    report: CurrentRecordView,
    *,
    scope: str,
    scaffold_id: str,
    region_id: str,
    fragment_id: str,
    reference_id: str,
) -> set[str] | None:
    allowed = None
    if scaffold_id:
        scaffold = next((s for s in report.scaffolds if s.id == scaffold_id), None)
        if scaffold is None:
            raise WebError(422, "sar_study_filter", "Scaffold is not in this study.")
        allowed = set(scaffold.molecule_ids)
    if fragment_id and not region_id:
        raise WebError(
            422, "sar_study_filter", "Fragment selection requires its exact region."
        )
    if reference_id and reference_id not in report.molecule_ids:
        raise WebError(422, "sar_study_filter", "Reference is not in this study.")
    regions = report.regions
    if region_id:
        regions = [s for s in regions if s.region.id == region_id]
        if not regions:
            raise WebError(422, "sar_study_filter", "Region is not in this study.")
        if reference_id and regions[0].region.molecule_id != reference_id:
            raise WebError(
                422, "sar_study_filter", "Region belongs to another reference."
            )
    elif reference_id:
        regions = [s for s in regions if s.region.molecule_id == reference_id]
    if region_id or reference_id:
        fragments = [
            (summary, fragment)
            for summary in regions
            for fragment in summary.fragments
            if (not fragment_id or fragment.id == fragment_id)
            and report.molecule_ids.intersection(fragment.molecule_ids)
        ]
        if fragment_id and not fragments:
            raise WebError(422, "sar_study_filter", "Fragment is not in this region.")
        changes = scope in {"changes", "strong_changes"}
        # A matched alias of the original fragment is zero structural change.
        # Keep it in normal tables/archives, not in modification-card counts.
        members = {
            mid
            for summary, fragment in fragments
            if not changes or not fragment.is_reference
            for mid in fragment.molecule_ids
            if not changes or mid != summary.region.molecule_id
        }
        allowed = members if allowed is None else allowed & members
    return allowed
