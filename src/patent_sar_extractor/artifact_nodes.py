"""Bounded ordered JSON identities for shared artifact objects, not science."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
# Existing rejected source-role packets can carry 208 levels plus their artifact
# envelope. Transport bounds must preserve those observations, not qualify them.
MAX_DEPTH = 256
MAX_NODES = 500_000
MAX_EDGES = 2_000_000
MAX_EXPANDED_NODES = 2_000_000


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


@dataclass(slots=True)
class JsonNode:
    kind: str
    body: object
    size: int
    height: int
    expanded_nodes: int
    uses: int = 0


class JsonGraph:
    """Hash unique ordered nodes once; detect input cycles before memoization."""

    def __init__(self):
        self.nodes: dict[str, JsonNode] = {}
        self.identities: dict[int, str] = {}
        self.scalars: dict[tuple, str] = {}
        self.active: set[int] = set()
        self.edges = 0

    def visit(self, value, depth=0) -> str:
        self.edges += 1
        if depth > MAX_DEPTH or self.edges > MAX_EDGES:
            raise ValueError("Shared JSON traversal exceeds its bounds")
        if not isinstance(value, (dict, list, tuple)):
            return self._scalar(value)
        identity = id(value)
        if identity in self.active:
            raise ValueError("Shared JSON cannot contain a cycle")
        if identity in self.identities:
            key = self.identities[identity]
            if depth + self.nodes[key].height > MAX_DEPTH:
                raise ValueError("Shared JSON traversal exceeds its bounds")
            self.nodes[key].uses += 1
            return key
        self.active.add(identity)
        try:
            if isinstance(value, dict):
                entries, names = [], set()
                for raw_key, item in value.items():
                    key = self._object_key(raw_key)
                    if key in names:
                        raise ValueError(
                            "Shared JSON object has competing normalized keys"
                        )
                    names.add(key)
                    entries.append((key, self.visit(item, depth + 1)))
                body = tuple(entries)
                size = (
                    2
                    + max(0, len(body) - 1)
                    + sum(
                        len(compact_json(key).encode("utf-8"))
                        + 1
                        + self.nodes[child].size
                        for key, child in body
                    )
                )
                kind = "object"
            else:
                body = tuple(self.visit(item, depth + 1) for item in value)
                size = (
                    2
                    + max(0, len(body) - 1)
                    + sum(self.nodes[child].size for child in body)
                )
                kind = "array"
            children = [child for _name, child in body] if kind == "object" else body
            height = 1 + max(
                (self.nodes[child].height for child in children), default=-1
            )
            count = 1 + sum(self.nodes[child].expanded_nodes for child in children)
            key = self._add(kind, body, size, height, count)
            self.identities[identity] = key
            return key
        finally:
            self.active.remove(identity)

    @staticmethod
    def _object_key(key):
        if isinstance(key, str):
            return key
        if key is None or type(key) in (bool, int, float):
            return compact_json(key)
        raise ValueError("Shared JSON object has a non-JSON key")

    def _scalar(self, value):
        kind = type(value).__name__
        if type(value) not in (type(None), bool, int, float, str) or (
            type(value) is float and not math.isfinite(value)
        ):
            raise ValueError("Shared JSON contains a non-JSON or non-finite value")
        # Python equates -0.0 with 0.0; JSON source spelling must remain distinct.
        token = value.hex() if type(value) is float else value
        cached = (kind, token)
        if cached in self.scalars:
            key = self.scalars[cached]
            self.nodes[key].uses += 1
            return key
        size = len(compact_json(value).encode("utf-8"))
        if size > MAX_ARTIFACT_BYTES:
            raise ValueError("Shared JSON literal exceeds its bound")
        key = self._add(kind, value, size, 0, 1)
        self.scalars[cached] = key
        return key

    def _add(self, kind, body, size, height, count):
        if size > MAX_EXPANDED_BYTES:
            raise ValueError("Shared JSON logical expansion exceeds its bound")
        if count > MAX_EXPANDED_NODES:
            raise ValueError("Shared JSON node expansion exceeds its bound")
        key = hashlib.sha256(compact_json([kind, body]).encode("utf-8")).hexdigest()
        if key not in self.nodes:
            if len(self.nodes) >= MAX_NODES:
                raise ValueError("Shared JSON unique node count exceeds its bound")
            self.nodes[key] = JsonNode(kind, body, size, height, count)
        self.nodes[key].uses += 1
        return key

    def materialize(self, key):
        """Return ordinary JSON containers, never aliases between saved records."""
        node = self.nodes[key]
        if node.kind == "object":
            return {name: self.materialize(child) for name, child in node.body}
        if node.kind == "array":
            return [self.materialize(child) for child in node.body]
        return node.body
