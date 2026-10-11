"""Canonical port-labelled aromatic subgraphs, never standalone molecules."""

import re
from typing import Any

from rdkit import Chem, rdBase

from .errors import SARInputError
from .limits import MAX_ATOMS, MAX_BONDS, MAX_SMILES_CHARS


def read_graph_notation(value: object):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_SMILES_CHARS
        or re.search(r"\s|\|", value)
    ):
        raise SARInputError("fragment_graph_invalid")
    params: Any = Chem.SmilesParserParams()
    params.sanitize, params.removeHs = False, False
    params.allowCXSMILES, params.parseName = False, False
    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(value, params)
        if mol is None or not 1 <= mol.GetNumAtoms() <= MAX_ATOMS + MAX_BONDS:
            raise SARInputError("fragment_graph_invalid")
        if mol.GetNumBonds() > MAX_BONDS or any(
            atom.HasQuery() for atom in mol.GetAtoms()
        ):
            raise SARInputError("fragment_graph_invalid")
        ports = [atom for atom in mol.GetAtoms() if atom.GetAtomicNum() == 0]
        if not ports or any(
            not 1 <= atom.GetAtomMapNum() <= MAX_ATOMS or atom.GetDegree() != 1
            for atom in ports
        ):
            raise SARInputError("fragment_graph_invalid")
        if not any(atom.GetIsAromatic() for atom in mol.GetAtoms()):
            raise SARInputError("fragment_graph_invalid")
        # These are partial ring graphs. Perceiving their topology/cache for
        # serialization/drawing is not sanitization or chemical eligibility.
        mol.UpdatePropertyCache(strict=False)
        Chem.GetSymmSSSR(mol)
    return mol


def graph_notation(mol, atoms):
    with rdBase.BlockLogs():
        # Input is an already validated original graph with caller-created
        # labelled ports. The canonical subgraph writer is the identity; do not
        # parse/recanonicalize each index key as if it were a standalone species.
        return Chem.MolFragmentToSmiles(
            mol,
            atomsToUse=sorted(atoms),
            canonical=True,
            isomericSmiles=True,
            allHsExplicit=True,
            allBondsExplicit=True,
        )
