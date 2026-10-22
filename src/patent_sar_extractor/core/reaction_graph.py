"""A complete directed source-arrow graph must have exactly one terminal node."""

import math
from collections import defaultdict, deque

from .reaction_arrows import contained, segment_bounds, vector_arrows
from .reaction_connections import visible_endpoint
from .reaction_heads import head_bounds
from .reaction_vectors import valid_rectangle, validate_vectors
from .source_geometry import overlaps

MAX_REACTION_DIAGRAMS = 256


def _page_edges(observation, diagrams, protected_regions, uncertainty=None):
    validate_vectors(observation)
    if any(
        not valid_rectangle(diagram["bbox"], observation["page_size"])
        or not contained(diagram["bbox"], observation["bounds"])
        for diagram in diagrams
    ):
        raise ValueError("A reaction drawing leaves its complete original source")
    uncertainty = {} if uncertainty is None else uncertainty
    if not isinstance(uncertainty, dict) or any(
        type(index) is not int
        or not 0 <= index < len(observation["segments"])
        or type(error) not in {int, float}
        or not math.isfinite(error)
        or not 0 <= error <= math.hypot(*observation["page_size"])
        for index, error in uncertainty.items()
    ):
        raise ValueError("Invalid original arrow coordinate uncertainty")
    if observation["version"] == 3 and (
        set(uncertainty) != set(range(len(observation["segments"])))
        or any(error <= 0 for error in uncertainty.values())
    ):
        raise ValueError("Pixel reaction geometry lost its coordinate uncertainty")
    # Binary source adapters check whole connected components against original
    # crop regions BEFORE projection. Do not turn coordinate-error padding into
    # fictitious extra diagram ink. Independently owned foreign regions remain
    # protected here, and all ordinary native crop guards remain unchanged.
    arrow_regions = (
        [
            region
            for region in protected_regions
            if not any(region == d["bbox"] for d in diagrams)
        ]
        if observation["version"] == 3
        else protected_regions
    )
    arrows = vector_arrows(observation, arrow_regions, uncertainty=uncertainty)
    edges = []
    for arrow in arrows:
        tail, tip = arrow["tail"], arrow["tip"]
        length = math.dist(tail, tip)
        errors = [(uncertainty or {}).get(i, 0.0) for i in arrow["segments"]]
        error = max(errors, default=0.0)
        if error and length < 4 * error:
            raise ValueError("Pixel shaft is too short to establish a stable direction")
        direction = [(tip[i] - tail[i]) / length for i in range(2)]
        start, left = visible_endpoint(
            tail,
            [-v for v in direction],
            diagrams,
            length,
            error=error,
            source_bounds=observation["bounds"],
        )
        end, right = visible_endpoint(
            tip,
            direction,
            diagrams,
            length,
            error=error,
            source_bounds=observation["bounds"],
        )
        if start == end:
            raise ValueError("Native arrow cannot connect a drawing to itself")
        for connector in (left, right):
            if error and not contained(connector, observation["bounds"]):
                raise ValueError(
                    "Pixel connection uncertainty leaves its source window"
                )
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


def terminal_reaction_source(
    candidates, pages, *, source_regions=None, endpoint_uncertainty=None
):
    """All candidates participate; disconnected, cyclic and multiple ends refuse."""
    if not 2 <= len(candidates) <= MAX_REACTION_DIAGRAMS or not all(
        c["inside"] for c in candidates
    ):
        raise ValueError("A native reaction requires its complete bounded drawings")
    nodes = {c["structure_id"] for c in candidates}
    if len(nodes) != len(candidates):
        raise ValueError("Native reaction contains duplicate source identities")
    if endpoint_uncertainty is not None and (
        not isinstance(endpoint_uncertainty, dict)
        or set(endpoint_uncertainty) != {page["page_no"] for page in pages}
    ):
        raise ValueError("Reaction uncertainty page inventory differs from its sources")
    outgoing, incoming = defaultdict(set), defaultdict(set)
    observed = set()
    for page in pages:
        diagrams = [c for c in candidates if c["page_no"] == page["page_no"]]
        protected = (source_regions or {}).get(
            page["page_no"], [d["bbox"] for d in diagrams]
        )
        for first, last in _page_edges(
            page,
            diagrams,
            protected,
            (endpoint_uncertainty or {}).get(page["page_no"]),
        ):
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
