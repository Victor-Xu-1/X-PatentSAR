"""Bounded candidate sites; every comparison still needs the strict matcher.

Canonical cut backgrounds are only an index, never proof. All source records
remain in the study table. Up to three-cut connected regions and ordinary H are
supported, including aromatic and non-stereogenic multiple-bond boundaries.
H boundary stereo, stereogenic double-bond cuts and >3 ports are not exhaustive.
"""

from collections import Counter, defaultdict
from itertools import chain

from ..identifier_order import natural_identifier_key
from .errors import SARInputError
from .molecules import chemical_identity, read_molfile
from .prepared_graphs import GraphPool
from .site_cuts import candidate_cuts, hydrogen_cuts
from .site_plans import ordered_site_plans
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
    if type(pair_budget) is not int or not 0 <= pair_budget <= MAX_PAIRS:
        raise SARInputError("study_discovery_pair_limit")
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
    pool = GraphPool()
    proposals = ordered_site_plans(
        families,
        ordered,
        identities,
        dataset,
        manual_regions,
        pool,
        check,
        excluded,
    )
    sites, redundant = compact_proved_sites(
        proposals,
        ordered,
        pool,
        check,
        pair_budget=pair_budget,
        site_budget=MAX_SITES,
    )
    # Proof order differs from publication order. Preserve the exact prior
    # original-source IDs, names, candidate order and complete report shape.
    sites.sort(key=lambda item: int(item["region"]["name"][1:]))
    comparisons = sum(len(item["candidate_ids"]) for item in sites)
    return sites, {
        "method": "single-region-three-port-multiple-h-v6",
        "candidate_sites": len(sites),
        "candidate_comparisons": comparisons,
        "indexed_cuts": cuts,
        "examined_boundaries": boundaries,
        "indexed_hydrogen_sites": hydrogen_sites,
        "max_cut_bonds": 3,
        "aromatic_boundaries": True,
        "multiple_bond_boundaries": True,
        "redundant_proved_sites": redundant,
        "excluded": dict(excluded),
        "max_variable_atoms": MAX_VARIABLE,
        "max_variable_fraction": 0.4,
        "min_fixed_atoms": 6,
        "limitations": [
            "hydrogen_boundary_stereo_not_supported",
            "stereogenic_multiple_bond_boundaries_not_supported",
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
