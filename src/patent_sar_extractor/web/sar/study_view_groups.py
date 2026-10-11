"""Conserve source memberships while presenting current global potency bands."""

from collections import Counter, OrderedDict, defaultdict

from ..errors import WebError
from .study_models import StudyBin


class GroupBins:
    """One projection's immutable-domain preparation, not a cross-read cache."""

    def __init__(self, domain):
        self.domain = domain
        self._items = OrderedDict()

    def for_members(self, members):
        key = tuple(sorted(members))
        if key not in self._items:
            result = tuple(
                tuple(value.items())
                for value in self.domain.for_members(members)["bins"]
            )
            if len(key) <= 4096:
                self._items[key] = result
                while (
                    len(self._items) > 256
                    or sum(len(item) for item in self._items) > 4096
                ):
                    self._items.popitem(last=False)
            return [StudyBin.model_validate(dict(item)) for item in result]
        self._items.move_to_end(key)
        return [StudyBin.model_validate(dict(item)) for item in self._items[key]]


def _group(item, ids, states, bins):
    members = [identifier for identifier in item.molecule_ids if identifier in ids]
    return item.model_copy(
        update={
            "molecule_ids": members,
            "molecule_count": len(members),
            "strong_count": sum(states[identifier]["strong"] for identifier in members),
            "bins": bins.for_members(members),
        }
    )


def _region(summary, selected, ids, states, bins):
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
    counts = Counter(pair["match_status"] for pair in selected)
    outcomes = defaultdict(Counter)
    for pair in selected:
        if pair["match_status"] == "matched":
            outcomes[pair["fragment_id"]][pair["comparison"]] += 1
    fragments = []
    for original in summary.fragments:
        fragment = _group(original, ids, states, bins)
        if not fragment.molecule_ids:
            continue
        changes = outcomes[fragment.id]
        fragments.append(
            fragment.model_copy(
                update={
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
    return summary.model_copy(
        update={
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


def current_groups(captured, ids, domain, states, pairs):
    bins = GroupBins(domain)
    indexed = defaultdict(list)
    for pair in pairs:
        if pair["molecule_id"] in ids:
            indexed[pair["region_id"]].append(pair)
    scaffolds = [
        _group(item, ids, states, bins)
        for item in captured.scaffolds
        if ids.intersection(item.molecule_ids)
    ]
    regions = [
        _region(summary, indexed[summary.region.id], ids, states, bins)
        for summary in captured.regions
        if summary.region.molecule_id in ids
    ]
    return scaffolds, regions
