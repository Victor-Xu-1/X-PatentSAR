"""Conserve source memberships while presenting current global potency bands."""

from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass

from ..errors import WebError
from .study_models import StudyRegionSummary, StudyScaffold
from .study_projection_models import (
    CurrentStudyBin,
    CurrentStudyFragment,
    CurrentStudyRegion,
    CurrentStudyScaffold,
)


class GroupBins:
    """One projection's immutable-domain preparation, not a cross-read cache."""

    def __init__(self, domain):
        self.domain = domain
        self._items = OrderedDict()
        self._member_references = 0

    def for_members(self, members):
        key = tuple(sorted(members))
        if key not in self._items:
            result = tuple(
                tuple(value.items())
                for value in self.domain.for_members(members)["bins"]
            )
            if len(key) <= 4096:
                self._items[key] = result
                self._member_references += len(key)
                while len(self._items) > 256 or self._member_references > 4096:
                    removed, _ = self._items.popitem(last=False)
                    self._member_references -= len(removed)
            return [CurrentStudyBin(**dict(item)) for item in result]
        self._items.move_to_end(key)
        return [CurrentStudyBin(**dict(item)) for item in self._items[key]]


def _group_fields(members, states, bins):
    return {
        "molecule_ids": members,
        "molecule_count": len(members),
        "strong_count": sum(states[identifier]["strong"] for identifier in members),
        "bins": bins.for_members(members),
    }


def _require_coverage(summary, selected, ids):
    pool = (
        (ids - {summary.region.molecule_id})
        if summary.comparison_pool is None
        else ids.intersection(summary.comparison_pool)
    )
    if {pair["molecule_id"] for pair in selected} != pool or len(selected) != len(pool):
        raise WebError(
            409,
            "sar_report_scope",
            "Published pairs do not cover the identified source pool.",
        )


def _region(summary, selected, ids, states, bins):
    counts = Counter(pair["match_status"] for pair in selected)
    outcomes = defaultdict(Counter)
    for pair in selected:
        if pair["match_status"] == "matched":
            outcomes[pair["fragment_id"]][pair["comparison"]] += 1
    fragments = []
    for original in summary.fragments:
        members = [
            identifier for identifier in original.molecule_ids if identifier in ids
        ]
        if not members:
            continue
        changes = outcomes[original.id]
        fragments.append(
            CurrentStudyFragment.model_validate(
                {
                    **original.__dict__,
                    **_group_fields(members, states, bins),
                    "better": changes["better"],
                    "worse": changes["worse"],
                    "missing": changes["missing"],
                    "indeterminate": sum(
                        value
                        for key, value in changes.items()
                        if key not in {"better", "worse", "equal", "missing"}
                    ),
                }
            )
        )
    return CurrentStudyRegion.model_validate(
        {
            **summary.__dict__,
            **{
                key: counts[key]
                for key in ("matched", "not_matched", "ambiguous", "ineligible")
            },
            "fragments": fragments,
            "comparison_pool": None
            if summary.comparison_pool is None
            else [mid for mid in summary.comparison_pool if mid in ids],
            "no_variation": len(fragments) == 1,
            "comparable": sum(
                pair["match_status"] == "matched"
                and pair["comparison"] in {"better", "worse", "equal"}
                for pair in selected
            ),
        }
    )


@dataclass(frozen=True)
class GroupScope:
    """Read-only captured memberships after every current pool is checked."""

    scaffolds: list[StudyScaffold]
    regions: list[StudyRegionSummary]
    pairs: dict[str, list[dict]]


def source_groups(captured, ids, pairs) -> GroupScope:
    indexed = defaultdict(list)
    for pair in pairs:
        if pair["molecule_id"] in ids:
            indexed[pair["region_id"]].append(pair)
    scaffolds = [
        item for item in captured.scaffolds if ids.intersection(item.molecule_ids)
    ]
    regions = [
        summary for summary in captured.regions if summary.region.molecule_id in ids
    ]
    for summary in regions:
        _require_coverage(summary, indexed[summary.region.id], ids)
    return GroupScope(scaffolds, regions, indexed)


def current_groups(captured, ids, domain, states, pairs):
    scope = source_groups(captured, ids, pairs)
    bins = GroupBins(domain)
    scaffolds = [
        CurrentStudyScaffold.model_validate(
            {
                **item.__dict__,
                **_group_fields(
                    [
                        identifier
                        for identifier in item.molecule_ids
                        if identifier in ids
                    ],
                    states,
                    bins,
                ),
            }
        )
        for item in scope.scaffolds
    ]
    regions = [
        _region(summary, scope.pairs[summary.region.id], ids, states, bins)
        for summary in scope.regions
    ]
    return scaffolds, regions
