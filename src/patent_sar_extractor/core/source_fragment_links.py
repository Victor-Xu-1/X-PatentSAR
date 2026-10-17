"""Unique adjacent original row links, recomputed from retained source facts."""

from .activity_continuation_policy import (
    caption_prefix,
    compatible_columns,
    continuation_prefix,
)
from .activity_grid_roles import characterization_roles
from .activity_headers import context_from_text
from .printed_identifiers import identifier_key
from .source_fragment_context import boundary_texts
from .source_role_fragments import fragment_texts

MAX_LINK_COMPARISONS = 4096


def _row_complete(previous, bottom, current, top):
    roles = previous["role_scope"]["roles"]
    if roles["columns"] != current["role_scope"]["roles"]["columns"]:
        return False
    row = []
    for column, role in enumerate(roles["columns"]):
        a = fragment_texts(previous, bottom, column)
        b = fragment_texts(current, top, column)
        if a is None or b is None:
            return False
        left, right = a[0], b[0]
        if role == "identifier" and left.strip() and right.strip():
            key = identifier_key(left, wrapped=True, terminal_period=True)
            if not key or key != identifier_key(
                right, wrapped=True, terminal_period=True
            ):
                return False
            row.append(left)  # Both literal IDs remain separately retained in source.
        else:
            row.append("\n".join(text for text in (left, right) if text.strip()))
    source = previous["role_scope"]
    matrix = [*source["observations"][0]["matrix"], row]
    return characterization_roles(matrix, source["prefix"]) == roles


def _compatible(previous, bottom, current, top):
    a, b = previous["grid_edges"], current["grid_edges"]
    if not (
        previous["original_pdf_sha256"] == current["original_pdf_sha256"]
        and current["page_no"] == previous["page_no"] + 1
        and bottom["bbox"][3] >= a["page_size"][1] / 2
        and top["bbox"][1] < 150
        and compatible_columns(a["xs"], b["xs"])
    ):
        return False
    suffix, prefix = (
        boundary_texts(previous, "suffix"),
        boundary_texts(current, "prefix"),
    )
    if (
        suffix is None
        or prefix is None
        or not all(continuation_prefix(text) for text in suffix)
    ):
        return False
    old_context = context_from_text(previous["role_scope"]["prefix"])
    if not all(
        continuation_prefix(text)
        or old_context.table_id
        and caption_prefix(
            text, old_context.table_id, old_context.raw_caption, continued=True
        )
        for text in prefix
    ):
        return False
    return _row_complete(previous, bottom, current, top)


def resolved_fragments(regions):
    """No stored link/complete flag can bypass current original replay."""
    nodes, tops = {}, {}
    for region in regions:
        for index, fragment in enumerate(region.get("row_fragments", [])):
            key = region["region_id"], index
            nodes[key] = region, fragment
            if fragment["edge"] == "top":
                tops.setdefault(region["page_no"], []).append(key)
    edges, inbound, comparisons = {}, {}, 0
    for key, (region, fragment) in nodes.items():
        if fragment["edge"] != "bottom":
            continue
        for target in tops.get(region["page_no"] + 1, []):
            comparisons += 1
            if comparisons > MAX_LINK_COMPARISONS:
                raise ValueError(
                    "Original open-row link inventory exceeds its comparison bound"
                )
            following, top = nodes[target]
            if _compatible(region, fragment, following, top):
                edges.setdefault(key, set()).add(target)
                inbound.setdefault(target, set()).add(key)
    result = set()
    for key, targets in edges.items():
        if len(targets) == 1:
            target = next(iter(targets))
            if len(inbound[target]) == 1:
                result.update((key, target))
    return result
