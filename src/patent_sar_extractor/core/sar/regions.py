"""Connected, nonempty variable regions with a nonempty attached fixed graph."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from rdkit import Chem

from .errors import SARInputError

BondKey = tuple[str, bool]
AttachmentKey = tuple[tuple[int, BondKey], ...]


def bond_key(bond: Chem.Bond) -> BondKey:
    return str(bond.GetBondType()), bond.GetIsAromatic()


def connected(mol: Chem.Mol, indices: frozenset[int]) -> bool:
    if not indices:
        return False
    seen, pending = set(), [min(indices)]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(
            a.GetIdx()
            for a in mol.GetAtomWithIdx(current).GetNeighbors()
            if a.GetIdx() in indices and a.GetIdx() not in seen
        )
    return seen == indices


def selection(mol: Chem.Mol, atom_indices: Sequence[int]) -> frozenset[int]:
    if (
        not isinstance(atom_indices, (list, tuple))
        or not atom_indices
        or len(atom_indices) > mol.GetNumAtoms()
    ):
        raise SARInputError("region_invalid_indices")
    if any(type(i) is not int or not 0 <= i < mol.GetNumAtoms() for i in atom_indices):
        raise SARInputError("region_invalid_indices")
    selected = frozenset(atom_indices)
    if len(selected) != len(atom_indices):
        raise SARInputError("region_duplicate_indices")
    if len(selected) == mol.GetNumAtoms():
        raise SARInputError("region_fixed_graph_empty")
    if not connected(mol, selected):
        raise SARInputError("region_disconnected")
    if not attachment_groups(mol, selected):
        raise SARInputError("region_not_attached")
    return selected


def attachment_groups(
    mol: Chem.Mol, variable: frozenset[int], inverse: dict[int, int] | None = None
) -> dict[AttachmentKey, list[int]]:
    """Group cut bonds by their actual variable endpoint, not arbitrary dummies.

    Every group records the complete fixed endpoints and bond types. A bridge
    endpoint cannot silently split into two endpoints, nor can ports migrate.
    """
    groups: dict[AttachmentKey, list[int]] = {}
    for index in sorted(variable):
        ports = []
        for bond in mol.GetAtomWithIdx(index).GetBonds():
            other = bond.GetOtherAtomIdx(index)
            if other not in variable:
                fixed = other if inverse is None else inverse[other]
                ports.append((fixed, bond_key(bond)))
        if ports:
            groups.setdefault(tuple(sorted(ports)), []).append(index)
    return groups


def attachment_mapping(
    reference: Chem.Mol,
    candidate: Chem.Mol,
    selected: frozenset[int],
    remaining: frozenset[int],
    mapping: dict[int, int],
) -> dict[int, int] | None:
    left = attachment_groups(reference, selected)
    right = attachment_groups(candidate, remaining, {v: k for k, v in mapping.items()})
    if Counter({key: len(values) for key, values in left.items()}) != Counter(
        {key: len(values) for key, values in right.items()}
    ):
        return None
    # Nonunique port endpoints cannot prove a boundary stereochemical mapping.
    return {
        values[0]: right[key][0] for key, values in left.items() if len(values) == 1
    }
