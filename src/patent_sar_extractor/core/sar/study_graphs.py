"""Pure port-labelled cut identities and descriptive (never proof) scaffolds."""

from __future__ import annotations

import hashlib

from rdkit import Chem, rdBase
from rdkit.Chem.Scaffolds import MurckoScaffold

from .errors import SARInputError
from .molecules import chemical_identity, read_molfile
from .regions import selection


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def cut_identity(
    molfile: str, variable_indices: list[int], attachment_mapping: list[list[int]]
) -> dict:
    """Label cut dummies by immutable reference fixed endpoints, not embedding order.

    Repeated ports to one anchor share its label but preserve multiplicity and
    bond types. Isotopes/charges/stereo/components are retained on both sides.
    Partial aromatic rings have no supported independent fragment identity.
    """
    mol = read_molfile(molfile)
    variable = selection(mol, variable_indices)
    labels = {candidate: reference + 1 for reference, candidate in attachment_mapping}
    if len(labels) != len(attachment_mapping) or any(
        label <= 0 for label in labels.values()
    ):
        raise SARInputError("study_attachment_identity")
    cuts = []
    for bond in mol.GetBonds():
        left, right = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        if (left in variable) == (right in variable):
            continue
        fixed = right if left in variable else left
        if fixed not in labels:
            raise SARInputError("study_attachment_identity")
        if bond.GetIsAromatic():
            raise SARInputError("study_aromatic_cut_unsupported")
        cuts.append((bond.GetIdx(), fixed, left in variable))
    if {fixed for _, fixed, _ in cuts} != set(labels):
        raise SARInputError("study_attachment_identity")
    with rdBase.BlockLogs():
        cut = Chem.FragmentOnBonds(
            mol, [index for index, _, _ in cuts], dummyLabels=[(0, 0)] * len(cuts)
        )
        included = set(variable)
        for offset, (_, fixed, begin_variable) in enumerate(cuts):
            # RDKit appends the begin-replacement dummy, then end-replacement.
            first, second = (
                mol.GetNumAtoms() + 2 * offset,
                mol.GetNumAtoms() + 2 * offset + 1,
            )
            for index in (first, second):
                cut.GetAtomWithIdx(index).SetAtomMapNum(labels[fixed])
            included.add(second if begin_variable else first)
        variable_smiles = Chem.MolFragmentToSmiles(
            cut, atomsToUse=sorted(included), canonical=True, isomericSmiles=True
        )
        fixed_smiles = Chem.MolFragmentToSmiles(
            cut,
            atomsToUse=sorted(set(range(cut.GetNumAtoms())) - included),
            canonical=True,
            isomericSmiles=True,
        )
        variable_mol = Chem.MolFromSmiles(variable_smiles)
        fixed_mol = Chem.MolFromSmiles(fixed_smiles)
        if variable_mol is None or fixed_mol is None:
            raise SARInputError("study_fragment_unsupported")
        # Normalize component serialization as well as atom serialization; no
        # component is removed and every port map remains part of the identity.
        variable_smiles = Chem.MolToSmiles(
            variable_mol, canonical=True, isomericSmiles=True
        )
        fixed_smiles = Chem.MolToSmiles(fixed_mol, canonical=True, isomericSmiles=True)
    return {
        "id": _sha("port-fragment-v1:" + variable_smiles),
        "smiles": variable_smiles,
        "fixed_background_sha256": _sha("port-background-v1:" + fixed_smiles),
    }


def reference_cut(molfile: str, atom_indices: list[int]) -> dict:
    mol = read_molfile(molfile)
    variable = selection(mol, atom_indices)
    anchors = sorted(
        {
            bond.GetOtherAtomIdx(index)
            for index in variable
            for bond in mol.GetAtomWithIdx(index).GetBonds()
            if bond.GetOtherAtomIdx(index) not in variable
        }
    )
    return cut_identity(molfile, atom_indices, [[index, index] for index in anchors])


def graph_description(molfile: str) -> dict:
    mol = read_molfile(molfile)
    canonical = chemical_identity(mol)
    scaffold = MurckoScaffold.GetScaffoldForMol(mol)
    cyclic = bool(scaffold.GetNumAtoms())
    smiles = Chem.MolToSmiles(scaffold, isomericSmiles=True) if cyclic else canonical
    kind = "murcko_descriptive" if cyclic else "acyclic_full_graph"
    warnings = []
    if not cyclic:
        warnings.append("acyclic_full_graph_not_shared_core")
    if len(Chem.GetMolFrags(mol)) > 1:
        warnings.append("scaffold_components_descriptive")
    potential = Chem.FindPotentialStereo(mol, cleanIt=False, flagPossible=True)
    if any(item.specified != Chem.StereoSpecified.Specified for item in potential):
        warnings.append("stereochemistry_unassigned")
    return {
        "canonical_smiles": canonical,
        "scaffold_id": _sha(kind + ":" + smiles),
        "scaffold_smiles": smiles,
        "scaffold_kind": kind,
        "reasons": warnings,
    }
