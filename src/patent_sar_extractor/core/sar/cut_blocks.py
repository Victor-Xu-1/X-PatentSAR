"""Bounded original-graph bridges and edge blocks for candidate topology only."""


def _search(adjacency, blocked, *, blocks):
    entered, low = [-1] * len(adjacency), [0] * len(adjacency)
    clock, bridges, groups, stack = 0, set(), [], []

    def visit(node, parent_edge):
        nonlocal clock
        entered[node] = low[node] = clock
        clock += 1
        for other, edge in adjacency[node]:
            if edge in blocked or edge == parent_edge:
                continue
            if entered[other] == -1:
                if blocks:
                    stack.append(edge)
                visit(other, edge)
                low[node] = min(low[node], low[other])
                if low[other] > entered[node]:
                    bridges.add(edge)
                if blocks and low[other] >= entered[node]:
                    group = set()
                    while stack:
                        removed = stack.pop()
                        group.add(removed)
                        if removed == edge:
                            break
                    if len(group) > 1:
                        groups.append(frozenset(group))
            else:
                low[node] = min(low[node], entered[other])
                if blocks and entered[other] < entered[node]:
                    stack.append(edge)

    for node in range(len(adjacency)):
        if entered[node] == -1:
            visit(node, -1)
    return bridges, groups


def bridges(adjacency, blocked=()):
    return _search(adjacency, blocked, blocks=False)[0]


def cycle_blocks(adjacency):
    return _search(adjacency, (), blocks=True)[1]
