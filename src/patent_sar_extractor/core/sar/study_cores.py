"""User-confirmed descriptive cores sharing the bounded exact graph proof."""

from __future__ import annotations

from dataclasses import dataclass

from rdkit import Chem

from .errors import SARInputError
from .graphs import Graph, graph
from .matching import _compare_graphs
from .molecules import read_molfile
from .regions import attachment_groups, connected
from .stereo import boundary_supported
from .study_graphs import reference_cut
from .study_statistics import distribution


@dataclass(frozen=True)
class ConfirmedCore:
    reference: Graph
    variable: frozenset[int]
    anchors: frozenset[int]
    smiles: str

    def membership(self, molfile: str) -> dict:
        try:
            candidate = graph(read_molfile(molfile))
        except SARInputError as error:
            return {"assigned": False, "reasons": [error.code]}
        proof = _compare_graphs(
            self.reference, candidate, self.variable, self.anchors, membership=True
        )
        return {
            "assigned": proof["match_status"] == "matched",
            "reasons": proof["reasons"],
        }


def compile_core(molfile: str, indices: list[int]) -> ConfirmedCore:
    reference = graph(read_molfile(molfile))
    selected = frozenset(indices)
    if (
        not indices
        or len(selected) != len(indices)
        or any(
            type(index) is not int or not 0 <= index < reference.mol.GetNumAtoms()
            for index in indices
        )
        or (
            len(selected) != reference.mol.GetNumAtoms()
            and not connected(reference.mol, selected)
        )
    ):
        raise SARInputError("study_core_selection")
    # Independent original components (e.g. counterions) remain fixed evidence;
    # membership never gains coverage by silently stripping/replacing salts.
    spectators = {
        index
        for component in Chem.GetMolFrags(reference.mol)
        if not selected.intersection(component)
        for index in component
    }
    fixed = selected | spectators
    variable = frozenset(range(reference.mol.GetNumAtoms())) - fixed
    if not boundary_supported(reference, variable):
        raise SARInputError("unsupported_boundary_bond_stereo")
    anchors = frozenset(
        endpoint
        for key in attachment_groups(reference.mol, variable)
        for endpoint, _ in key
    )
    has_ports = any(
        bond.GetOtherAtomIdx(index) not in selected
        for index in selected
        for bond in reference.mol.GetAtomWithIdx(index).GetBonds()
    )
    smiles = (
        reference_cut(molfile, indices)["smiles"]
        if has_ports
        else Chem.MolFragmentToSmiles(
            reference.mol,
            atomsToUse=sorted(selected),
            canonical=True,
            isomericSmiles=True,
        )
    )
    return ConfirmedCore(reference, variable, anchors, smiles)


def confirmed_core_summaries(
    cores, molecules, observations, policy, assessments, check=lambda: None
):
    indexed = {molecule["id"]: molecule for molecule in molecules}
    summaries, assignments, warnings = [], {}, set()
    for core in cores:
        reference = indexed[core["molecule_id"]]
        matcher = compile_core(reference["molfile"], core["atom_indices"])
        members = []
        for molecule in molecules:
            check()
            if not molecule["eligible"] or not molecule.get("molfile"):
                continue
            result = matcher.membership(molecule["molfile"])
            if result["assigned"]:
                members.append(molecule["id"])
                assignments.setdefault(molecule["id"], []).append(core["id"])
            elif any(
                code.startswith(("mapping_", "ambiguous_"))
                for code in result["reasons"]
            ):
                warnings.add("confirmed_core_membership_unresolved")
        summaries.append(
            {
                "id": core["id"],
                "smiles": matcher.smiles,
                "molecule_count": len(members),
                "molecule_ids": members,
                "strong_count": sum(assessments[item]["strong"] for item in members),
                "bins": distribution(members, observations, policy, assessments)[
                    "bins"
                ],
                "descriptive_only": True,
                "assignment_kind": "confirmed_core",
                "core_region_id": core["id"],
            }
        )
    if any(len(values) > 1 for values in assignments.values()):
        warnings.add("confirmed_core_groups_overlap")
    return summaries, warnings
