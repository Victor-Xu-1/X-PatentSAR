"""Original continuation captions, immutable anchor columns and bounded reads."""

import re

from .activity_context_geometry import valid_box
from .activity_grid_role_observation import observe_role_cells
from .printed_identifiers import identifier_key
from .source_cell_tokens import cell_lines, cell_text
from .source_section_roles import section_body_boundary
from .source_table_markers import table_body_boundary
from .source_window_chunks import (
    observe_source_window,
    observe_window_sources,
    validate_source_projection,
    validate_source_window,
    window_source_tokens,
)
from .structure_column_context import column_context_band
from .structure_column_scopes import original_column_axes, original_column_roles
from .unruled_continuation_titles import (
    continuation_identity,
    continuation_nominees,
    qualified_table_key,
)
from .unruled_header_readings import original_header_readings


def continuation_axes(scope):
    xs, _ys = original_column_axes(scope["anchor_scope"])
    return xs, [scope["caption"]["bbox"][1], scope["caption"]["bbox"][3]]


def observe_continuation(page, tokens, nomination, anchor, parent):
    size = [page.rect.width, page.rect.height]
    left, right = column_context_band(anchor)
    bounds = [
        left,
        max(0, nomination["bbox"][1] - 4),
        right,
        min(size[1], nomination["bbox"][3] + 4),
    ]
    reading = observe_role_cells(
        page,
        {"xs": [left, right], "ys": [bounds[1], bounds[3]]},
        tokens,
        retain_frames=True,
    )
    if reading is None:
        raise ValueError("Original continuation caption exceeds its reading budget")
    return {
        "kind": "continued_unruled_columns",
        "version": 1,
        "original_pdf_sha256": anchor["original_pdf_sha256"],
        "page_no": page.number + 1,
        "page_size": size,
        "anchor_scope": anchor,
        "parent_region_id": parent["region_id"] if parent else "",
        "parent_page_no": parent["page_no"] if parent else None,
        "leading_context": observe_source_window(tokens, [0, 0, size[0], bounds[3]]),
        "caption": {
            "nomination": nomination,
            "bbox": bounds,
            "sources": observe_window_sources(tokens, bounds),
            "role_cells": reading,
        },
    }


def continuation_roles(scope):
    if not isinstance(scope, dict) or set(scope) != {
        "kind",
        "version",
        "original_pdf_sha256",
        "page_no",
        "page_size",
        "anchor_scope",
        "parent_region_id",
        "parent_page_no",
        "leading_context",
        "caption",
    }:
        raise ValueError("Malformed original unruled continuation scope")
    anchor = scope["anchor_scope"]
    if not isinstance(anchor, dict) or anchor.get("kind") not in {
        None,
        "original_ruled_columns",
    }:
        raise ValueError("A continuation must retain one nonrecursive original anchor")
    roles = original_column_roles(anchor)
    size = scope["page_size"]
    if (
        scope["kind"] != "continued_unruled_columns"
        or type(scope["version"]) is not int
        or scope["version"] != 1
        or type(scope["page_no"]) is not int
        or not anchor["page_no"] <= scope["page_no"] <= 20000
        or scope["original_pdf_sha256"] != anchor["original_pdf_sha256"]
        or not isinstance(size, list)
        or len(size) != 2
        or any(type(v) not in {int, float} or not 0 < v <= 100000 for v in size)
        or not isinstance(scope["parent_region_id"], str)
        or scope["parent_region_id"]
        and not re.fullmatch(r"[a-f0-9]{64}", scope["parent_region_id"])
        or not scope["parent_region_id"]
        and scope["parent_page_no"] is not None
        or scope["parent_region_id"]
        and (
            type(scope["parent_page_no"]) is not int
            or scope["parent_page_no"] not in {scope["page_no"], scope["page_no"] - 1}
            or scope["parent_page_no"] < anchor["page_no"]
        )
    ):
        raise ValueError("Invalid original unruled continuation identity")
    caption = scope["caption"]
    if not isinstance(caption, dict) or set(caption) != {
        "nomination",
        "bbox",
        "sources",
        "role_cells",
    }:
        raise ValueError("Malformed original continuation caption")
    bounds = caption["bbox"]
    left, right = column_context_band(anchor)
    if (
        not valid_box(bounds)
        or bounds[0] != left
        or bounds[2] != right
        or not 0 <= bounds[1] < bounds[3] < size[1]
    ):
        raise ValueError("Original continuation caption leaves its page")
    leading = [0, 0, size[0], bounds[3]]
    validate_source_window(scope["leading_context"], leading)
    tokens = window_source_tokens(scope["leading_context"], leading)
    if caption["nomination"] not in continuation_nominees(
        tokens,
        size,
        native_tokens=window_source_tokens(
            scope["leading_context"], leading, native=True
        ),
    ):
        raise ValueError(
            "Continuation nomination differs from complete original leading context"
        )
    box = caption["nomination"]["bbox"]
    if bounds != [left, max(0, box[1] - 4), right, min(size[1], box[3] + 4)]:
        raise ValueError("Original continuation caption clipping changed")
    if (
        anchor["page_no"] == scope["page_no"]
        and original_column_axes(anchor)[1][1] >= bounds[1]
    ):
        raise ValueError("Original continuation cannot precede its own column anchor")
    validate_source_projection(
        [{"bbox": bounds, "sources": caption["sources"]}],
        bounds,
        scope["leading_context"],
        leading,
    )
    texts = original_header_readings(
        caption["role_cells"],
        [left, right],
        [bounds[1], bounds[3]],
        caption["sources"],
        identity=continuation_identity,
    )
    if (
        roles is None
        or texts is None
        or size[0] != anchor["page_size"][0]
        or not scope["parent_region_id"]
    ):
        return None
    identity = continuation_identity(texts[0])
    if (
        not identity
        or identity[0] != qualified_table_key(anchor)
        or identity[1] not in {"unknown", roles["role"]}
    ):
        return None
    xs, ys = continuation_axes(scope)
    if scope["parent_page_no"] == scope["page_no"]:
        # Exact same-page boundary and full shared-source conservation are
        # independently replayed against the registered parent region.
        return {**roles, "xs": xs, "ys": ys}
    prefix = [left, 0, right, bounds[1]]
    for native in (False, True):
        prefix_tokens = window_source_tokens(
            scope["leading_context"], prefix, native=native
        )
        for line in cell_lines(prefix_tokens, prefix):
            text = cell_text(line, prefix)
            if table_body_boundary(text) or section_body_boundary(text):
                return None
        for identifier, _structure in roles["pairs"]:
            window = [xs[identifier], 0, xs[identifier + 1], bounds[1]]
            if any(
                identifier_key(
                    cell_text(line, window), wrapped=True, terminal_period=True
                )
                for line in cell_lines(prefix_tokens, window)
            ):
                return None
    return {**roles, "xs": xs, "ys": ys}
