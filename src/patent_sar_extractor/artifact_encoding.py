"""Bound the complete wire representation before allocating its JSON tree."""

from __future__ import annotations

from . import artifact_nodes as limits
from .artifact_nodes import compact_json

REFERENCE = "$shared"
READONLY = "$readonly"
LITERAL = "$literal"
RESERVED = ({REFERENCE}, {LITERAL}, {REFERENCE, READONLY})


def encode_graph(graph, root, *, marker, version, max_objects, min_bytes):
    catalog, measures = {}, {}

    def is_reference(key, reference, source_parent):
        node = graph.nodes[key]
        return reference and (
            (node.readonly and not source_parent)
            or (node.uses > 1 and node.size >= min_bytes)
        )

    def measure(key, *, reference=True, source_parent=False):
        node = graph.nodes[key]
        if is_reference(key, reference, source_parent):
            if key not in catalog:
                if len(catalog) >= max_objects:
                    raise ValueError("Shared JSON catalog exceeds its bound")
                catalog[key] = (0, 0)
                catalog[key] = measure(key, reference=False)
            token = {REFERENCE: key}
            if node.readonly and not source_parent:
                token[READONLY] = True
            return len(compact_json(token).encode("utf-8")), len(token) + 1
        if key in measures:
            return measures[key]
        if not node.container:
            result = node.size, 1
        else:
            kind = node.kind.removeprefix("readonly_")
            children = [
                measure(child, source_parent=node.readonly) for child in node.children
            ]
            size = 2 + max(0, len(children) - 1) + sum(item[0] for item in children)
            count = 1 + sum(item[1] for item in children)
            if kind == "object":
                size += sum(
                    len(compact_json(name).encode("utf-8")) + 1
                    for name, _child in node.body
                )
                if {name for name, _child in node.body} in RESERVED:
                    size += len(compact_json(LITERAL).encode("utf-8")) + 3
                    count += 1
            result = size, count
        if result[0] > limits.MAX_ARTIFACT_BYTES:
            raise ValueError("Shared JSON artifact exceeds its byte bound")
        if result[1] > limits.MAX_EXPANDED_NODES:
            raise ValueError("Shared JSON encoded node expansion exceeds its bound")
        measures[key] = result
        return result

    size, count = measure(root, reference=graph.nodes[root].readonly)
    if catalog:
        catalog_size = (
            2
            + max(0, len(catalog) - 1)
            + sum(
                len(compact_json(key).encode("utf-8")) + 1 + value[0]
                for key, value in catalog.items()
            )
        )
        declaration = (
            len(f'{{"version":{version},"objects":'.encode()) + catalog_size + 1
        )
        size += len(compact_json(marker).encode("utf-8")) + 2 + declaration
        count += 3 + sum(value[1] for value in catalog.values())
    if size > limits.MAX_ARTIFACT_BYTES:
        raise ValueError("Shared JSON artifact exceeds its byte bound")
    if count > limits.MAX_EXPANDED_NODES:
        raise ValueError("Shared JSON encoded node expansion exceeds its bound")

    def emit(key, *, reference=True, source_parent=False):
        node = graph.nodes[key]
        if is_reference(key, reference, source_parent):
            token = {REFERENCE: key}
            if node.readonly and not source_parent:
                token[READONLY] = True
            return token
        kind = node.kind.removeprefix("readonly_")
        if kind == "object":
            value = {
                name: emit(child, source_parent=node.readonly)
                for name, child in node.body
            }
            return {LITERAL: value} if set(value) in RESERVED else value
        if kind == "array":
            return [emit(child, source_parent=node.readonly) for child in node.body]
        return node.body

    if not catalog:
        return None
    encoded = emit(root, reference=graph.nodes[root].readonly)
    encoded[marker] = {
        "version": version,
        "objects": {key: emit(key, reference=False) for key in catalog},
    }
    return encoded
