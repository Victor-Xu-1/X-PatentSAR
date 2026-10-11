"""Bounded candidate sites; every comparison still needs the strict matcher.

Canonical cut backgrounds are only an index, never proof. All source records
remain in the study table. Ring/multi-port and implicit-H changes are not
enumerated here and must not be mistaken for an exhaustive chemical search.
"""

import hashlib
from collections import Counter, defaultdict
from collections.abc import Callable

from rdkit import Chem

from ..identifier_order import natural_identifier_key
from .errors import SARInputError
from .matching import compile_reference
from .molecules import chemical_identity, read_molfile

MAX_CUTS = 100000
MAX_SITES = 4096
MAX_PAIRS = 75000
MAX_VARIABLE = 32


def _cuts(mol, check: Callable):
    count = mol.GetNumAtoms()
    for bond in mol.GetBonds():
        check()
        if bond.IsInRing() or bond.GetBondType() != Chem.BondType.SINGLE:
            continue
        cut = Chem.FragmentOnBonds(mol, [bond.GetIdx()], dummyLabels=[(0, 0)])
        for atom in list(cut.GetAtoms())[count:]:
            atom.SetAtomMapNum(1)
        for component in Chem.GetMolFrags(cut):
            selected = tuple(index for index in component if index < count)
            if len(component) == len(selected):
                continue  # Spectator components remain frozen, not selected.
            if (
                not selected
                or len(selected) > MAX_VARIABLE
                or len(selected) > count * 0.4
            ):
                continue
            if count - len(selected) < 6:
                continue
            fixed = sorted(set(range(cut.GetNumAtoms())) - set(component))
            fragment = Chem.MolFragmentToSmiles(
                cut, atomsToUse=fixed, canonical=True, isomericSmiles=True
            )
            core = Chem.MolFromSmiles(fragment)
            if core is not None:
                yield (
                    Chem.MolToSmiles(core, canonical=True, isomericSmiles=True),
                    selected,
                )


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
    cuts = 0
    for row in ordered:
        check()
        if not row["eligible"] or not row.get("molfile"):
            excluded["source_structure_ineligible"] += 1
            continue
        mol = read_molfile(row["molfile"])
        identities[row["id"]] = chemical_identity(mol)
        for key, selection in _cuts(mol, check):
            cuts += 1
            if cuts > MAX_CUTS:
                raise SARInputError("study_discovery_cut_limit")
            previous = families[key].get(row["id"])
            if previous is not None and previous != selection:
                families[key][row["id"]] = ()  # No arbitrary symmetric site.
            elif row["id"] not in families[key]:
                families[key][row["id"]] = selection
    by_id = {row["id"]: row for row in ordered}
    manual = {
        (region["molecule_id"], tuple(sorted(region["atom_indices"])))
        for region in manual_regions
    }
    sites, comparisons = [], 0
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
            selection = members[mid]
            candidates = [
                other
                for other in members
                if other != mid and identities[other] != identities[mid]
            ]
            if not candidates or (mid, tuple(sorted(selection))) in manual:
                continue
            try:
                compile_reference(by_id[mid]["molfile"], selection)
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
                        "attachment_count": 1,
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
            if len(sites) > MAX_SITES or comparisons > pair_budget:
                raise SARInputError("study_discovery_pair_limit")
    return sites, {
        "method": "single-non-ring-bond-v1",
        "candidate_sites": len(sites),
        "candidate_comparisons": comparisons,
        "indexed_cuts": cuts,
        "excluded": dict(excluded),
        "max_variable_atoms": MAX_VARIABLE,
        "max_variable_fraction": 0.4,
        "min_fixed_atoms": 6,
        "limitations": ["implicit_h_not_enumerated", "ring_multiport_not_enumerated"],
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
