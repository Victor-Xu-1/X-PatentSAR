"""Lossless in-artifact shared JSON; hashes do not establish scientific truth."""

from __future__ import annotations

import json
import re

from .artifact_decoding import decode_graph
from .artifact_encoding import LITERAL, READONLY, REFERENCE, encode_graph
from .artifact_nodes import JsonGraph
from .contracts import SHARED_JSON_VERSION

MARKER = "_shared_json"
VERSION = SHARED_JSON_VERSION
MAX_SHARED_OBJECTS = 100_000
MIN_SHARED_BYTES = 512

__all__ = (
    "LITERAL",
    "MARKER",
    "READONLY",
    "REFERENCE",
    "expand_shared_json",
    "pack_shared_json",
    "read_artifact_json",
)


def pack_shared_json(payload: dict) -> dict:
    """Ordinary values stay independent; explicit source views remain immutable."""
    if not isinstance(payload, dict) or MARKER in payload:
        raise ValueError("Shared JSON requires an unencoded artifact object")
    graph = JsonGraph()
    root = graph.visit(payload)
    graph.validate_allocation(root)
    encoded = encode_graph(
        graph,
        root,
        marker=MARKER,
        version=VERSION,
        max_objects=MAX_SHARED_OBJECTS,
        min_bytes=MIN_SHARED_BYTES,
    )
    return payload if encoded is None else encoded


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
        or declaration["version"] not in (1, VERSION)
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
    return decode_graph(
        {key: value for key, value in payload.items() if key != MARKER},
        catalog,
        version=declaration["version"],
    )


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
