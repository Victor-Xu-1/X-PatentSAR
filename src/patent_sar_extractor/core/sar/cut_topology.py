"""Exact one/two/three-edge connected partitions, never chemistry/SAR proof."""

from itertools import combinations, product

from rdkit import Chem

from .cut_blocks import bridges, cycle_blocks


def _reachable(adjacency, start, blocked):
    mask, pending = 0, [start]
    while pending:
        node = pending.pop()
        if mask & (1 << node):
            continue
        mask |= 1 << node
        pending.extend(other for other, edge in adjacency[node] if edge not in blocked)
    return mask


def _crosses(mask, boundary, bonds):
    return mask and all(
        bool(mask & (1 << begin)) != bool(mask & (1 << end))
        for begin, end in (bonds[edge] for edge in boundary)
    )


def _bridge_partitions(boundary, sides, bonds):
    seen = set()
    for choices in product(*(sides[edge] for edge in boundary)):
        mask = choices[0]
        for side in choices[1:]:
            mask &= side
        if mask not in seen and _crosses(mask, boundary, bonds):
            seen.add(mask)
            yield mask


def boundary_regions(mol, inspect):
    """Yield original-atom bitmasks attached across exactly the supplied cuts.

    Original bridge sides are cached bitmasks. Ring pairs form two-port regions;
    one further bridge can restrict those to three ports. Three ring edges are
    considered only when the third becomes a bridge after two cuts. Two original
    bridges plus one ring edge cannot separate a connected region. No arbitrary
    all-edge triple fragmentation; spectators never enter selected regions.
    Single, double, triple and aromatic bonds are candidate boundaries. These
    are topology proposals only; potential double-bond stereo is still refused
    by the unchanged strict reference/candidate matcher.
    """
    adjacency = tuple(
        tuple(
            (bond.GetOtherAtomIdx(atom.GetIdx()), bond.GetIdx())
            for bond in atom.GetBonds()
        )
        for atom in mol.GetAtoms()
    )
    components = {}
    for component in Chem.GetMolFrags(mol):
        mask = sum(1 << index for index in component)
        components.update((index, mask) for index in component)
    bonds = {
        bond.GetIdx(): (bond.GetBeginAtomIdx(), bond.GetEndAtomIdx())
        for bond in mol.GetBonds()
        if bond.GetBondType()
        in {Chem.BondType.SINGLE, Chem.BondType.DOUBLE, Chem.BondType.TRIPLE}
        or bond.GetIsAromatic()
    }
    original_bridges = bridges(adjacency)
    sides = {}
    for edge in sorted(set(bonds) & original_bridges):
        inspect()
        begin, _ = bonds[edge]
        side = _reachable(adjacency, begin, {edge})
        sides[edge] = side, components[begin] ^ side
        for mask in sides[edge]:
            yield (edge,), mask

    for size in (2, 3):
        for boundary in combinations(sides, size):
            inspect()
            if len({components[bonds[edge][0]] for edge in boundary}) != 1:
                continue
            for mask in _bridge_partitions(boundary, sides, bonds):
                yield boundary, mask

    ring_edges = set(bonds) - original_bridges
    blocks = [sorted(group & ring_edges) for group in cycle_blocks(adjacency)]
    block_by_edge = {edge: set(group) for group in blocks for edge in group}
    for first in sorted(ring_edges):
        inspect()
        partners = bridges(adjacency, {first}) & block_by_edge[first]
        for second in sorted(edge for edge in partners if edge > first):
            inspect()
            begin, _ = bonds[first]
            side = _reachable(adjacency, begin, {first, second})
            for mask in (side, components[begin] ^ side):
                if _crosses(mask, (first, second), bonds):
                    yield (first, second), mask
                    for bridge, bridge_sides in sides.items():
                        # Only an internal bridge can create one additional port.
                        if not all(mask & (1 << atom) for atom in bonds[bridge]):
                            continue
                        inspect()
                        boundary = tuple(sorted((first, second, bridge)))
                        for bridge_side in bridge_sides:
                            selected = mask & bridge_side
                            if _crosses(selected, boundary, bonds):
                                yield boundary, selected

    for group in blocks:
        for first, second in combinations(group, 2):
            inspect()
            partners = bridges(adjacency, {first, second}) & set(group)
            for third in sorted(edge for edge in partners if edge > second):
                inspect()
                boundary = first, second, third
                # Complements may contain several disconnected components.
                for start in bonds[third]:
                    selected = _reachable(adjacency, start, set(boundary))
                    if _crosses(selected, boundary, bonds):
                        yield boundary, selected
