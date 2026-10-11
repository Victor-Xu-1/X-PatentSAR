"""Conserve source memberships while presenting current global potency bands."""

from collections import Counter, defaultdict

from ..errors import WebError
from .study_models import StudyBin


def _group(item, ids, domain, states):
    members = [identifier for identifier in item.molecule_ids if identifier in ids]
    return item.model_copy(
        update={
            "molecule_ids": members,
            "molecule_count": len(members),
            "strong_count": sum(states[identifier]["strong"] for identifier in members),
            "bins": [
                StudyBin.model_validate(value)
                for value in domain.for_members(members)["bins"]
            ],
        }
    )


def _region(summary, selected, ids, domain, states):
    if {pair["molecule_id"] for pair in selected} != ids - {
        summary.region.molecule_id
    } or len(selected) != len(ids) - 1:
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
        fragment = _group(original, ids, domain, states)
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
            "no_variation": len(fragments) == 1,
            "comparable": sum(
                pair["match_status"] == "matched"
                and pair["comparison"] in {"better", "worse", "equal"}
                for pair in selected
            ),
        }
    )


def current_groups(captured, ids, domain, states, pairs):
    indexed = defaultdict(list)
    for pair in pairs:
        if pair["molecule_id"] in ids:
            indexed[pair["region_id"]].append(pair)
    scaffolds = [
        _group(item, ids, domain, states)
        for item in captured.scaffolds
        if ids.intersection(item.molecule_ids)
    ]
    regions = [
        _region(summary, indexed[summary.region.id], ids, domain, states)
        for summary in captured.regions
        if summary.region.molecule_id in ids
    ]
    return scaffolds, regions
