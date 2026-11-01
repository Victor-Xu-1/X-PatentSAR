"""Preflight allocations before restoring independent records/shared source views."""

from __future__ import annotations

from . import artifact_nodes as limits
from .artifact_immutable import readonly_container


def validate_allocation(graph, root):
    ordinary = graph.nodes[root].expanded_nodes
    source_pool, visited = set(), set()

    def inspect(key, source=False):
        source |= graph.nodes[key].readonly
        context = (key, source)
        if context in visited:
            return
        visited.add(context)
        node = graph.nodes[key]
        if source:
            source_pool.add(key)
        for child in node.children:
            inspect(child, source)

    inspect(root)
    if ordinary + len(source_pool) > limits.MAX_EXPANDED_NODES:
        raise ValueError("Shared JSON node expansion exceeds its bound")


def materialize(graph, root):
    validate_allocation(graph, root)
    cache = {}

    def build(key, *, source_parent=False):
        node = graph.nodes[key]
        if not node.container:
            return node.body
        if node.readonly and source_parent and key in cache:
            return cache[key]
        kind = node.kind.removeprefix("readonly_")
        if kind == "object":
            contents = (
                (name, build(child, source_parent=node.readonly))
                for name, child in node.body
            )
            value = (
                readonly_container(kind, contents, byte_size=node.size)
                if node.readonly
                else dict(contents)
            )
        else:
            contents = (
                build(child, source_parent=node.readonly) for child in node.body
            )
            value = (
                readonly_container(kind, contents, byte_size=node.size)
                if node.readonly
                else list(contents)
            )
        # A boundary gets its own immutable wrapper. A later bounded deepcopy of
        # distinct records cannot acquire aliases through copy's outer memo.
        if node.readonly and source_parent:
            cache[key] = value
        return value

    return build(root)
