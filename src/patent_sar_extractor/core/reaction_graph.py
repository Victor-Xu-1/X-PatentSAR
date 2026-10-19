"""A complete directed native-arrow graph must have exactly one terminal node."""

import math
from collections import defaultdict, deque

from .reaction_arrows import contained, segment_bounds, vector_arrows
from .reaction_heads import head_bounds
from .reaction_vectors import validate_vectors
from .source_geometry import overlaps

MAX_REACTION_DIAGRAMS = 256


def _ray_entry(point, direction, box):
    lower, upper = 0.0, math.inf
    for axis in range(2):
        if abs(direction[axis]) < 1e-9:
            if not box[axis] < point[axis] < box[axis + 2]:
                return None
            continue
        ends = [(box[axis + i] - point[axis]) / direction[axis] for i in (0, 2)]
        lower, upper = max(lower, min(ends)), min(upper, max(ends))
    return lower if 0 < lower < upper else None


def _visible_endpoint(point, direction, diagrams, length):
    entries = [
        (distance, d)
        for d in diagrams
        if (distance := _ray_entry(point, direction, d["bbox"])) is not None
    ]
    entries.sort(key=lambda pair: pair[0])
    if (
        not entries
        or entries[0][0] > length
        or len(entries) > 1
        and entries[1][0] - entries[0][0] <= 0.5
    ):
        raise ValueError("Native arrow endpoint has no unique local visible drawing")
    distance, diagram = entries[0]
    end = [point[i] + direction[i] * distance for i in range(2)]
    return diagram["structure_id"], segment_bounds([*point, *end])


def _page_edges(observation, diagrams, protected_regions):
    validate_vectors(observation)
    arrows = vector_arrows(observation, protected_regions)
    edges = []
    for arrow in arrows:
        tail, tip = arrow["tail"], arrow["tip"]
        length = math.dist(tail, tip)
        direction = [(tip[i] - tail[i]) / length for i in range(2)]
        start, left = _visible_endpoint(tail, [-v for v in direction], diagrams, length)
        end, right = _visible_endpoint(tip, direction, diagrams, length)
        if start == end:
            raise ValueError("Native arrow cannot connect a drawing to itself")
        for connector in (left, right):
            if any(
                overlaps(connector, region)
                and not any(region == d["bbox"] for d in diagrams)
                for region in protected_regions
            ):
                raise ValueError(
                    "Native arrow connection crosses an independent source"
                )
            if any(
                overlaps(connector, blocker)
                and not any(contained(blocker, d["bbox"]) for d in diagrams)
                for blocker in observation["blockers"]
            ):
                raise ValueError("Native arrow connection is blocked by source ink")
            if any(
                i not in arrow["segments"]
                and overlaps(connector, segment_bounds(segment))
                and not any(
                    contained(segment_bounds(segment, 0), d["bbox"]) for d in diagrams
                )
                for i, segment in enumerate(observation["segments"])
            ):
                raise ValueError("Native arrow connection has competing source strokes")
            if any(
                i not in arrow["heads"]
                and overlaps(connector, head_bounds(head))
                and not any(contained(head_bounds(head), d["bbox"]) for d in diagrams)
                for i, head in enumerate(observation["filled_heads"])
            ):
                raise ValueError(
                    "Native arrow connection has competing filled source ink"
                )
        edges.append((start, end))
    return edges


def terminal_reaction_source(candidates, pages, *, source_regions=None):
    """All candidates participate; disconnected, cyclic and multiple ends refuse."""
    if not 2 <= len(candidates) <= MAX_REACTION_DIAGRAMS or not all(
        c["inside"] for c in candidates
    ):
        raise ValueError("A native reaction requires its complete bounded drawings")
    nodes = {c["structure_id"] for c in candidates}
    if len(nodes) != len(candidates):
        raise ValueError("Native reaction contains duplicate source identities")
    outgoing, incoming = defaultdict(set), defaultdict(set)
    observed = set()
    for page in pages:
        diagrams = [c for c in candidates if c["page_no"] == page["page_no"]]
        protected = (source_regions or {}).get(
            page["page_no"], [d["bbox"] for d in diagrams]
        )
        for first, last in _page_edges(page, diagrams, protected):
            outgoing[first].add(last)
            incoming[last].add(first)
            observed.update((first, last))
    terminals = nodes - set(outgoing)
    if observed != nodes or len(terminals) != 1:
        raise ValueError("Native route has orphan drawings or multiple terminals")
    degrees = {node: len(incoming[node]) for node in nodes}
    ready = deque(node for node, degree in degrees.items() if not degree)
    visited = set()
    while ready:
        node = ready.popleft()
        visited.add(node)
        for following in outgoing[node]:
            degrees[following] -= 1
            if degrees[following] == 0:
                ready.append(following)
    if visited != nodes:
        raise ValueError("Native reaction contains a cycle")
    # In a finite acyclic graph every node reaches a sink. A single sink and
    # conservation of every node establish one connected terminal, not a rank.
    return next(iter(terminals))
