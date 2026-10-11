"""Connected, nonempty variable regions with a nonempty attached fixed graph."""

from __future__ import annotations

from collections.abc import Sequence

from rdkit import Chem

from .errors import SARInputError

BondKey = tuple[str, bool]
AttachmentKey = tuple[tuple[int, BondKey], ...]
PortMap = dict[tuple[int, int], int]
Adjacency = Sequence[dict[int, BondKey]]
FixedPorts = dict[tuple[int, BondKey], list[int]]


def bond_key(bond: Chem.Bond) -> BondKey:
    return str(bond.GetBondType()), bond.GetIsAromatic()


def _links(mol: Chem.Mol, index: int, adjacency: Adjacency | None):
    if adjacency is not None:
        return adjacency[index].items()
    return (
        (bond.GetOtherAtomIdx(index), bond_key(bond))
        for bond in mol.GetAtomWithIdx(index).GetBonds()
    )


def connected(
    mol: Chem.Mol, indices: frozenset[int], *, adjacency: Adjacency | None = None
) -> bool:
    if not indices:
        return False
    seen, pending = set(), [min(indices)]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        neighbors = (
            adjacency[current]
            if adjacency is not None
            else (a.GetIdx() for a in mol.GetAtomWithIdx(current).GetNeighbors())
        )
        pending.extend(
            other for other in neighbors if other in indices and other not in seen
        )
    return seen == indices


def selection(
    mol: Chem.Mol, atom_indices: Sequence[int], *, adjacency: Adjacency | None = None
) -> frozenset[int]:
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
    if not connected(mol, selected, adjacency=adjacency):
        raise SARInputError("region_disconnected")
    if not attachment_groups(mol, selected, adjacency=adjacency):
        raise SARInputError("region_not_attached")
    return selected


def attachment_groups(
    mol: Chem.Mol,
    variable: frozenset[int],
    inverse: dict[int, int] | None = None,
    *,
    adjacency: Adjacency | None = None,
) -> dict[AttachmentKey, list[int]]:
    """Inventory actual cut bonds for region validation and fixed-anchor labels.

    Variable endpoint grouping is not a requirement that the selected internal
    graph keep the same size or topology. The proof below freezes fixed edges.
    """
    groups: dict[AttachmentKey, list[int]] = {}
    for index in sorted(variable):
        ports = []
        for other, key in _links(mol, index, adjacency):
            if other not in variable:
                fixed = other if inverse is None else inverse[other]
                ports.append((fixed, key))
        if ports:
            groups.setdefault(tuple(sorted(ports)), []).append(index)
    return groups


def fixed_ports(
    mol: Chem.Mol, variable: frozenset[int], *, adjacency: Adjacency | None = None
) -> FixedPorts:
    """Original fixed-anchor bond inventory; never an embedding or stereo proof."""
    groups: FixedPorts = {}
    for index in sorted(variable):
        for other, key in _links(mol, index, adjacency):
            if other not in variable:
                groups.setdefault((other, key), []).append(index)
    return groups


def attachment_mapping(
    reference: Chem.Mol,
    candidate: Chem.Mol,
    selected: frozenset[int],
    remaining: frozenset[int],
    mapping: dict[int, int],
    *,
    reference_ports: FixedPorts | None = None,
    candidate_ports: FixedPorts | None = None,
) -> PortMap | None:
    left = (
        reference_ports
        if reference_ports is not None
        else fixed_ports(reference, selected)
    )
    actual = (
        candidate_ports
        if candidate_ports is not None
        else fixed_ports(candidate, remaining)
    )
    inverse = {v: k for k, v in mapping.items()}
    right = {(inverse[fixed], bond): values for (fixed, bond), values in actual.items()}
    if {key: len(values) for key, values in left.items()} != {
        key: len(values) for key, values in right.items()
    }:
        return None
    # Freeze the anchor/bond/multiplicity, not internal variable vertices. A
    # one-atom bridge can extend into two vertices without moving either anchor.
    # Indistinguishable multiple ligands at the SAME fixed stereo centre cannot
    # supply arbitrary parity; consumers refuse when such a mapping is needed.
    return {
        (key[0], values[0]): right[key][0]
        for key, values in left.items()
        if len(values) == 1
    }
