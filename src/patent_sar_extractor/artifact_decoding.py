"""Validate versioned references directly into the single bounded JSON graph."""

from __future__ import annotations

from .artifact_encoding import LITERAL, READONLY, REFERENCE
from .artifact_nodes import MAX_DEPTH, MAX_EDGES, JsonGraph


def decode_graph(payload, catalog, *, version):
    graph = JsonGraph()
    cache, active, used = {}, set(), set()
    edges = 0
    references = (
        ({REFERENCE}, {REFERENCE, READONLY}) if version >= 2 else ({REFERENCE},)
    )

    def walk(value, depth=0, *, literal=False, readonly=False):
        nonlocal edges
        edges += 1
        if depth > MAX_DEPTH or edges > MAX_EDGES:
            raise ValueError("Shared JSON traversal exceeds its bounds")
        if isinstance(value, dict):
            if not literal and set(value) in references:
                explicit = READONLY in value
                if explicit and value[READONLY] is not True:
                    raise ValueError("Malformed shared JSON source-view reference")
                source = readonly or explicit
                key = value[REFERENCE]
                if not isinstance(key, str) or key not in catalog:
                    raise ValueError("Shared JSON reference is missing")
                if key in active:
                    raise ValueError("Shared JSON reference cycle")
                used.add(key)
                if key not in cache:
                    if (
                        isinstance(catalog[key], dict)
                        and set(catalog[key]) in references
                    ):
                        raise ValueError(
                            "Shared JSON catalog cannot contain an alias-only node"
                        )
                    active.add(key)
                    restored = walk(catalog[key], depth, readonly=source)
                    if restored != key:
                        raise ValueError("Shared JSON content identity differs")
                    cache[key] = restored
                    active.remove(key)
                node = graph.nodes[key]
                if (node.container and node.readonly != source) or (
                    explicit and not node.container
                ):
                    raise ValueError("Shared JSON content mutability differs")
                if depth + node.height > MAX_DEPTH:
                    raise ValueError("Shared JSON traversal exceeds its bounds")
                return key
            if not literal and set(value) == {LITERAL}:
                if not isinstance(value[LITERAL], dict):
                    raise ValueError("Malformed shared JSON literal object")
                return walk(value[LITERAL], depth, literal=True, readonly=readonly)
            body = tuple(
                (name, walk(item, depth + 1, readonly=readonly))
                for name, item in value.items()
            )
            return graph.container("object", body, readonly=readonly)
        if isinstance(value, list):
            body = tuple(walk(item, depth + 1, readonly=readonly) for item in value)
            return graph.container("array", body, readonly=readonly)
        return graph.scalar(value)

    root = walk(payload)
    if used != set(catalog):
        raise ValueError("Shared JSON contains unreachable objects")
    return graph.materialize(root)
