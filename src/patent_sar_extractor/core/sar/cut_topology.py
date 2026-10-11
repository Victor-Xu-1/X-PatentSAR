"""Exact one/two/three-edge connected partitions, never chemistry/SAR proof."""

from itertools import combinations, product

from rdkit import Chem


def _reachable(adjacency, start, blocked):
    mask, pending = 0, [start]
    while pending:
        node = pending.pop()
        if mask & (1 << node):
            continue
        mask |= 1 << node
        pending.extend(other for other, edge in adjacency[node] if edge not in blocked)
    return mask


def _bridges(adjacency, blocked=()):
    """Tarjan bridge search, bounded by the existing maximum 512 input atoms."""
    entered = [-1] * len(adjacency)
    low = [0] * len(adjacency)
    clock, result = 0, set()

    def visit(node, parent_edge):
        nonlocal clock
        entered[node] = low[node] = clock
        clock += 1
        for other, edge in adjacency[node]:
            if edge in blocked or edge == parent_edge:
                continue
            if entered[other] == -1:
                visit(other, edge)
                low[node] = min(low[node], low[other])
                if low[other] > entered[node]:
                    result.add(edge)
            else:
                low[node] = min(low[node], entered[other])

    for node in range(len(adjacency)):
        if entered[node] == -1:
            visit(node, -1)
    return result


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
        if bond.GetBondType() == Chem.BondType.SINGLE and not bond.GetIsAromatic()
    }
    bridges = _bridges(adjacency)
    sides = {}
    for edge in sorted(set(bonds) & bridges):
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

    ring_edges = set(bonds) - bridges
    for first in sorted(ring_edges):
        inspect()
        partners = _bridges(adjacency, {first}) & ring_edges
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

    for first, second in combinations(sorted(ring_edges), 2):
        inspect()
        if components[bonds[first][0]] != components[bonds[second][0]]:
            continue
        partners = _bridges(adjacency, {first, second}) & ring_edges
        for third in sorted(edge for edge in partners if edge > second):
            inspect()
            boundary = first, second, third
            # Complements may contain several disconnected components; inspect
            # the actual components at both endpoints of the last bridge instead.
            for start in bonds[third]:
                selected = _reachable(adjacency, start, set(boundary))
                if _crosses(selected, boundary, bonds):
                    yield boundary, selected
