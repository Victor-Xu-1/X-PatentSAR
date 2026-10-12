"""Small depiction-quality guard, never a molecular eligibility/acceptance rule."""

from __future__ import annotations

import math

from rdkit import Chem


def crowded_chain(mol: Chem.Mol, variable: frozenset[int]) -> bool:
    """Refuse acute non-ring two-bond folds; genuine small rings are untouched."""
    conformer = mol.GetConformer()
    for index in variable:
        atom = mol.GetAtomWithIdx(index)
        if atom.IsInRing() or atom.GetDegree() != 2:
            continue
        center = conformer.GetAtomPosition(index)
        a, b = (
            conformer.GetAtomPosition(other.GetIdx()) - center
            for other in atom.GetNeighbors()
        )
        size = a.Length() * b.Length()
        if size <= 1e-12 or a.DotProduct(b) / size > math.cos(math.radians(70)):
            return True
    return False
