"""Exact one/two-edge connected partitions; no fragment chemistry or SAR proof."""

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


def boundary_regions(mol, inspect):
    """Yield original-atom bitmasks attached across exactly the supplied cuts.

    For two original bridges, intersect cached sides instead of repeatedly
    fragmenting full molecules. For ring edges, a partner is considered only
    when it becomes a bridge after the first cut. A bridge/ring combination
    cannot delimit a two-edge connected region and is never brute-forced.
    Spectator components remain outside every selected region.
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

    for first, second in combinations(sides, 2):
        inspect()
        # No connected variable region spans distinct molecular components.
        if components[bonds[first][0]] != components[bonds[second][0]]:
            continue
        seen = set()
        for left, right in product(sides[first], sides[second]):
            mask = left & right
            if (
                mask
                and mask not in seen
                and all(
                    bool(mask & (1 << begin)) != bool(mask & (1 << end))
                    for begin, end in (bonds[first], bonds[second])
                )
            ):
                seen.add(mask)
                yield (first, second), mask

    ring_edges = set(bonds) - bridges
    for first in sorted(ring_edges):
        inspect()
        partners = _bridges(adjacency, {first}) & ring_edges
        for second in sorted(edge for edge in partners if edge > first):
            inspect()
            begin, _ = bonds[first]
            side = _reachable(adjacency, begin, {first, second})
            for mask in (side, components[begin] ^ side):
                if mask and all(
                    bool(mask & (1 << start)) != bool(mask & (1 << end))
                    for start, end in (bonds[first], bonds[second])
                ):
                    yield (first, second), mask
