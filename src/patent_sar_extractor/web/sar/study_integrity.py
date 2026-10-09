"""Source-bound conservation checks, not a second scientific calculation path."""

from __future__ import annotations

from collections import Counter

from ...core.sar.study_contexts import context_catalog, context_identity
from ..errors import WebError
from .study_models import StudyReport


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WebError(502, "sar_result_invalid", message)


def verify_conservation(report: StudyReport, packet: dict) -> None:
    rows = packet["molecules"]
    _require(
        [item.model_dump() for item in report.contexts]
        == context_catalog(rows, packet["dataset"]["metrics"]),
        "Study experimental contexts differ from immutable source observations.",
    )
    counts = {
        row["id"]: Counter(context_identity(obs) for obs in row["observations"])
        for row in rows
    }
    identifiers = set(counts)
    selected = [policy.context_id for policy in report.policies]
    _require(
        [item.context_id for item in report.distributions] == selected,
        "Distribution coverage differs from selected policies.",
    )
    primary = selected[0]
    domains = {
        item.context_id: {(bin.kind, bin.label) for bin in item.bins}
        for item in report.distributions
    }

    def bins_valid(bins, members, context_id):
        _require(
            len(set(members)) == len(members) and set(members).issubset(identifiers),
            "Chart members differ from source identities.",
        )
        keys = [(item.kind, item.label) for item in bins]
        expected_observations = sum(counts[mid][context_id] for mid in members)
        _require(
            len(set(members)) == len(members)
            and set(members).issubset(identifiers)
            and len(set(keys)) == len(keys)
            and set(keys).issubset(domains[context_id])
            and all(item.molecules >= 0 and item.observations >= 0 for item in bins)
            and sum(item.molecules for item in bins) == len(members)
            and sum(item.observations for item in bins) == expected_observations,
            "Chart counts do not conserve source membership and raw measurements.",
        )

    for item in report.distributions:
        bins_valid(item.bins, list(identifiers), item.context_id)
        _require(
            item.observed_molecules + item.missing_molecules == len(rows)
            and item.missing_molecules
            == sum(bin.molecules for bin in item.bins if bin.kind == "missing")
            and item.observations == sum(bin.observations for bin in item.bins)
            and 0 <= item.strong_molecules <= item.observed_molecules
            and 0 <= item.unresolved_molecules <= item.observed_molecules,
            "Distribution totals differ from the whole source pool.",
        )
    murcko_members = []
    confirmed = set()
    for scaffold in report.scaffolds:
        bins_valid(scaffold.bins, scaffold.molecule_ids, primary)
        _require(
            scaffold.molecule_count == len(scaffold.molecule_ids)
            and 0 <= scaffold.strong_count <= scaffold.molecule_count,
            "Scaffold counts differ from source membership.",
        )
        if scaffold.assignment_kind == "murcko":
            murcko_members.extend(scaffold.molecule_ids)
        else:
            confirmed.add(scaffold.id)
            _require(
                scaffold.core_region_id == scaffold.id,
                "Confirmed core identity differs.",
            )
    _require(
        len(murcko_members) == len(rows)
        and set(murcko_members) == identifiers
        and confirmed == {core["id"] for core in packet["cores"]},
        "Scaffold/core groups omit source rows or requested cores.",
    )
    for summary in report.regions:
        members = []
        for fragment in summary.fragments:
            bins_valid(fragment.bins, fragment.molecule_ids, primary)
            members.extend(fragment.molecule_ids)
        _require(
            len(members) == len(set(members)) and len(members) == summary.matched + 1,
            "Fragment groups overlap or omit proved comparisons.",
        )
