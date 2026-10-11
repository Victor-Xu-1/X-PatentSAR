"""Bounded candidate sites; every comparison still needs the strict matcher.

Canonical cut backgrounds are only an index, never proof. All source records
remain in the study table. Up to three-cut connected regions and ordinary H are
supported; aromatic boundaries, H boundary stereo and >3 ports are not exhaustive.
"""

import hashlib
from collections import Counter, defaultdict
from itertools import chain

from ..identifier_order import natural_identifier_key
from .errors import SARInputError
from .matching import compile_reference
from .molecules import chemical_identity, read_molfile
from .prepared_graphs import GraphPool
from .site_cuts import candidate_cuts, hydrogen_cuts
from .site_reduction import compact_proved_sites

MAX_CUTS = 100000
MAX_SITES = 4096
MAX_PAIRS = 75000
MAX_VARIABLE = 32
MAX_BOUNDARIES = 500000


def discover_sites(
    rows, dataset, manual_regions=(), *, check=lambda: None, pair_budget=MAX_PAIRS
):
    """Return deterministic directed site plans, not accepted comparisons.

    Every distinct numbered reference can become a centre. All candidate IDs
    in a family are retained except unchanged complete graphs or ambiguous cut
    locations. Exceeding any resource bound refuses the whole result; it never
    publishes the first N sites as though they were complete.
    """
    families = defaultdict(dict)
    identities, excluded = {}, Counter()
    ordered = sorted(
        rows, key=lambda row: (natural_identifier_key(row["label"]), row["id"])
    )
    cuts, boundaries, hydrogen_sites = 0, 0, 0

    def inspect():
        nonlocal boundaries
        check()
        boundaries += 1
        if boundaries > MAX_BOUNDARIES:
            raise SARInputError("study_discovery_boundary_limit")

    for row in ordered:
        check()
        if not row["eligible"] or not row.get("molfile"):
            excluded["source_structure_ineligible"] += 1
            continue
        mol = read_molfile(row["molfile"])
        identities[row["id"]] = chemical_identity(mol)
        heavy_cuts = candidate_cuts(
            mol,
            inspect,
            excluded,
            max_variable=MAX_VARIABLE,
            max_fraction=0.4,
            min_fixed=6,
        )
        for key, selection, ports, hydrogen_anchor in chain(
            ((*cut, None) for cut in heavy_cuts),
            hydrogen_cuts(mol, inspect, excluded, min_fixed=6),
        ):
            cuts += 1
            hydrogen_sites += hydrogen_anchor is not None
            if cuts > MAX_CUTS:
                raise SARInputError("study_discovery_cut_limit")
            previous = families[key].get(row["id"])
            if previous is not None and previous != (selection, ports, hydrogen_anchor):
                families[key][row["id"]] = ()  # No arbitrary symmetric site.
            elif row["id"] not in families[key]:
                families[key][row["id"]] = (selection, ports, hydrogen_anchor)
    by_id = {row["id"]: row for row in ordered}
    manual = {
        (
            region["molecule_id"],
            tuple(sorted(region["atom_indices"])),
            region.get("hydrogen_anchor"),
        )
        for region in manual_regions
    }
    sites, comparisons = [], 0
    pool = GraphPool()
    for key, members in sorted(families.items()):
        check()
        if len(members) < 2:
            continue
        excluded["ambiguous_cut_location"] += sum(
            not atoms for atoms in members.values()
        )
        members = {mid: atoms for mid, atoms in members.items() if atoms}
        for mid in sorted(
            members,
            key=lambda identifier: (
                natural_identifier_key(by_id[identifier]["label"]),
                identifier,
            ),
        ):
            selection, ports, hydrogen_anchor = members[mid]
            candidates = [
                other
                for other in members
                if other != mid and identities[other] != identities[mid]
            ]
            if (
                not candidates
                or (mid, tuple(sorted(selection)), hydrogen_anchor) in manual
            ):
                continue
            try:
                compile_reference(
                    by_id[mid]["molfile"],
                    selection,
                    hydrogen_anchor=hydrogen_anchor,
                    pool=pool,
                )
            except ValueError:
                excluded["unsupported_reference_boundary"] += 1
                continue
            seed = "\0".join(
                (
                    dataset["id"],
                    str(dataset["revision"]),
                    mid,
                    by_id[mid]["graph_sha256"],
                    key,
                    ",".join(map(str, selection)),
                    "ordinary_hydrogen:" + str(hydrogen_anchor)
                    if hydrogen_anchor is not None
                    else "original_atoms",
                )
            )
            region_id = hashlib.sha256(seed.encode()).hexdigest()[:32]
            sites.append(
                {
                    "region": {
                        "id": region_id,
                        "dataset_id": dataset["id"],
                        "dataset_revision": dataset["revision"],
                        "molecule_id": mid,
                        "graph_sha256": by_id[mid]["graph_sha256"],
                        "atom_indices": list(selection),
                        "hydrogen_anchor": hydrogen_anchor,
                        "attachment_count": ports,
                        "kind": "variable",
                        "name": f"S{len(sites) + 1}",
                        "created_at": dataset.get("created_at", "source-derived"),
                    },
                    "candidate_ids": sorted(
                        candidates,
                        key=lambda other: (
                            natural_identifier_key(by_id[other]["label"]),
                            other,
                        ),
                    ),
                }
            )
            comparisons += len(candidates)
            if comparisons > pair_budget:
                raise SARInputError("study_discovery_pair_limit")
    sites, redundant = compact_proved_sites(sites, ordered, pool, check)
    comparisons = sum(len(item["candidate_ids"]) for item in sites)
    if len(sites) > MAX_SITES:
        raise SARInputError("study_discovery_pair_limit")
    return sites, {
        "method": "single-region-three-port-aromatic-h-v5",
        "candidate_sites": len(sites),
        "candidate_comparisons": comparisons,
        "indexed_cuts": cuts,
        "examined_boundaries": boundaries,
        "indexed_hydrogen_sites": hydrogen_sites,
        "max_cut_bonds": 3,
        "aromatic_boundaries": True,
        "redundant_proved_sites": redundant,
        "excluded": dict(excluded),
        "max_variable_atoms": MAX_VARIABLE,
        "max_variable_fraction": 0.4,
        "min_fixed_atoms": 6,
        "limitations": [
            "hydrogen_boundary_stereo_not_supported",
            "more_than_three_ports_not_enumerated",
        ],
    }


def comparison_plan(rows, regions, dataset, request, check):
    plans = [
        {
            "region": region,
            "candidate_ids": [
                row["id"] for row in rows if row["id"] != region["molecule_id"]
            ],
            "origin": "manual",
        }
        for region in regions
    ]
    coverage = None
    if request.get("discover_single_sites", False):
        remaining = MAX_PAIRS - sum(len(plan["candidate_ids"]) for plan in plans)
        derived, coverage = discover_sites(
            rows, dataset, regions, check=check, pair_budget=remaining
        )
        plans.extend({**plan, "origin": "single_site"} for plan in derived)
    return plans, coverage
