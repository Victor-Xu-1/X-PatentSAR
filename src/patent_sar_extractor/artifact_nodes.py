"""Bounded ordered JSON identities for shared artifact objects, not science."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from .artifact_immutable import FrozenDict, FrozenList

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

    @property
    def readonly(self):
        return self.kind.startswith("readonly_")

    @property
    def container(self):
        return self.kind.removeprefix("readonly_") in ("object", "array")

    @property
    def children(self):
        if self.kind.removeprefix("readonly_") == "object":
            return (child for _name, child in self.body)
        return iter(self.body) if self.container else iter(())


class JsonGraph:
    """Hash unique ordered nodes once; detect input cycles before memoization."""

    def __init__(self, *, max_depth=None, transform=None):
        self.nodes: dict[str, JsonNode] = {}
        self.identities: dict[tuple[int, bool], str] = {}
        self.scalars: dict[tuple, str] = {}
        self.active: set[int] = set()
        self.edges = 0
        self.max_depth = MAX_DEPTH if max_depth is None else min(max_depth, MAX_DEPTH)
        self.transform = transform

    def visit(
        self, value, depth=0, *, readonly=False, mutable=False, field=None
    ) -> str:
        self.edges += 1
        if depth > self.max_depth or self.edges > MAX_EDGES:
            raise ValueError("Shared JSON traversal exceeds its bounds")
        if self.transform is not None:
            value = self.transform(value, field)
        if not isinstance(value, (dict, list, tuple)):
            return self.scalar(value)
        identity = id(value)
        readonly = not mutable and (
            readonly or isinstance(value, (FrozenDict, FrozenList))
        )
        context = (identity, readonly)
        if identity in self.active:
            raise ValueError("Shared JSON cannot contain a cycle")
        if context in self.identities:
            key = self.identities[context]
            if depth + self.nodes[key].height > self.max_depth:
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
                    entries.append(
                        (
                            key,
                            self.visit(
                                item,
                                depth + 1,
                                readonly=readonly,
                                mutable=mutable,
                                field=key,
                            ),
                        )
                    )
                body = tuple(entries)
                kind = "object"
            else:
                body = tuple(
                    self.visit(item, depth + 1, readonly=readonly, mutable=mutable)
                    for item in value
                )
                kind = "array"
            key = self.container(kind, body, readonly=readonly)
            self.identities[context] = key
            return key
        finally:
            self.active.remove(identity)

    def container(self, kind, body, *, readonly=False):
        """One identity/budget authority for input traversal and wire decoding."""
        children = tuple(child for _name, child in body) if kind == "object" else body
        names_size = (
            sum(len(compact_json(name).encode("utf-8")) + 1 for name, _child in body)
            if kind == "object"
            else 0
        )
        size = (
            2
            + max(0, len(body) - 1)
            + names_size
            + sum(self.nodes[child].size for child in children)
        )
        height = 1 + max((self.nodes[child].height for child in children), default=-1)
        # A read-only view allocates a shared graph, not mutable copies at each
        # reference. The materializer separately budgets that whole shared pool.
        count = (
            1
            if readonly
            else 1 + sum(self.nodes[child].expanded_nodes for child in children)
        )
        return self._add(
            f"readonly_{kind}" if readonly else kind, body, size, height, count
        )

    @staticmethod
    def _object_key(key):
        if isinstance(key, str):
            return key
        if key is None or type(key) in (bool, int, float):
            return compact_json(key)
        raise ValueError("Shared JSON object has a non-JSON key")

    def scalar(self, value):
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
        """Ordinary records stay independent; only explicit source views share."""
        from .artifact_materialization import materialize

        return materialize(self, key)

    def validate_allocation(self, key):
        from .artifact_materialization import validate_allocation

        validate_allocation(self, key)
