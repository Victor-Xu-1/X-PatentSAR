"""Lossless in-artifact shared JSON; hashes do not establish scientific truth."""

from __future__ import annotations

import json
import re

from .artifact_nodes import MAX_DEPTH, MAX_EDGES, JsonGraph
from .contracts import SHARED_JSON_VERSION

MARKER = "_shared_json"
VERSION = SHARED_JSON_VERSION
MAX_SHARED_OBJECTS = 100_000
MIN_SHARED_BYTES = 512
REFERENCE = "$shared"
LITERAL = "$literal"


def pack_shared_json(payload: dict) -> dict:
    """Keep source order/types/content; intern repeated substantial nodes only."""
    if not isinstance(payload, dict) or MARKER in payload:
        raise ValueError("Shared JSON requires an unencoded artifact object")
    graph = JsonGraph()
    root = graph.visit(payload)
    catalog = {}

    def emit(key, *, reference=True):
        node = graph.nodes[key]
        if reference and node.uses > 1 and node.size >= MIN_SHARED_BYTES:
            if key not in catalog:
                if len(catalog) >= MAX_SHARED_OBJECTS:
                    raise ValueError("Shared JSON catalog exceeds its bound")
                catalog[key] = None
                catalog[key] = emit(key, reference=False)
            return {REFERENCE: key}
        if node.kind == "object":
            value = {name: emit(child) for name, child in node.body}
            return {LITERAL: value} if set(value) in ({REFERENCE}, {LITERAL}) else value
        if node.kind == "array":
            return [emit(child) for child in node.body]
        return node.body

    encoded = emit(root, reference=False)
    if catalog:
        encoded[MARKER] = {"version": VERSION, "objects": catalog}
        return encoded
    return payload


def expand_shared_json(payload, *, duplicate_keys=False):
    """Restore one validated DAG before unchanged domain/source acceptance."""
    if not isinstance(payload, dict) or MARKER not in payload:
        return payload
    declaration = payload[MARKER]
    if (
        duplicate_keys
        or not isinstance(declaration, dict)
        or set(declaration) != {"version", "objects"}
        or type(declaration["version"]) is not int
        or declaration["version"] != VERSION
        or not isinstance(declaration["objects"], dict)
        or not 1 <= len(declaration["objects"]) <= MAX_SHARED_OBJECTS
    ):
        raise ValueError("Malformed shared JSON catalog")
    catalog = declaration["objects"]
    if any(
        not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key)
        for key in catalog
    ):
        raise ValueError("Malformed shared JSON content identity")
    cache, active, used = {}, set(), set()
    graph = JsonGraph()
    edges = 0

    def walk(value, depth=0, *, literal=False):
        nonlocal edges
        edges += 1
        if depth > MAX_DEPTH or edges > MAX_EDGES:
            raise ValueError("Shared JSON traversal exceeds its bounds")
        if isinstance(value, dict):
            if not literal and set(value) == {REFERENCE}:
                key = value[REFERENCE]
                if not isinstance(key, str) or key not in catalog:
                    raise ValueError("Shared JSON reference is missing")
                if key in active:
                    raise ValueError("Shared JSON reference cycle")
                used.add(key)
                if key not in cache:
                    if isinstance(catalog[key], dict) and set(catalog[key]) == {
                        REFERENCE
                    }:
                        raise ValueError(
                            "Shared JSON catalog cannot contain an alias-only node"
                        )
                    active.add(key)
                    restored = walk(catalog[key], depth)
                    if graph.visit(restored) != key:
                        raise ValueError("Shared JSON content identity differs")
                    cache[key] = restored
                    active.remove(key)
                return cache[key]
            if not literal and set(value) == {LITERAL}:
                if not isinstance(value[LITERAL], dict):
                    raise ValueError("Malformed shared JSON literal object")
                return walk(value[LITERAL], depth, literal=True)
            return {key: walk(item, depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item, depth + 1) for item in value]
        return value

    restored = walk({key: value for key, value in payload.items() if key != MARKER})
    if used != set(catalog):
        raise ValueError("Shared JSON contains unreachable objects")
    root = graph.visit(restored)
    return graph.materialize(root)


def read_artifact_json(source, *, strict_numbers=False):
    """One parser for stream/native and bounded-byte/Web artifact readers."""
    duplicate = False

    def pairs(items):
        nonlocal duplicate
        result = {}
        for key, value in items:
            duplicate |= key in result
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("Non-finite JSON number")

    arguments = {"object_pairs_hook": pairs}
    if strict_numbers:
        arguments["parse_constant"] = nonfinite
    payload = (
        json.load(source, **arguments)
        if hasattr(source, "read")
        else json.loads(source, **arguments)
    )
    return expand_shared_json(payload, duplicate_keys=duplicate)
