"""Actual headerless physical scopes consume one registered original anchor."""

import re

from .activity_context_geometry import grid_axes
from .ruled_continuation_context import qualified_running_window, validate_page_grid
from .source_window_chunks import (
    observe_source_window,
    project_source_window,
    validate_source_window,
)
from .structure_column_context import column_context_band
from .structure_column_scopes import original_column_roles, original_columns_fit_frame

KIND = "continued_ruled_columns"


def observe_physical_continuation(page, tokens, grid, grids, original_sha):
    width = page.rect.width
    return {
        "kind": KIND,
        "version": 1,
        "original_pdf_sha256": original_sha,
        "page_no": page.number + 1,
        "page_size": [width, page.rect.height],
        "grid_axes": grid_axes(grid),
        "page_grids": [grid_axes(g) for g in grids],
        "leading_context": observe_source_window(tokens, [0, 0, width, grid["ys"][1]]),
        "anchor_scope": None,
        "parent_region_id": "",
        "parent_page_no": None,
        "context_start": 0,
    }


def physical_continuation_roles(scope):
    if not isinstance(scope, dict) or set(scope) != {
        "kind",
        "version",
        "original_pdf_sha256",
        "page_no",
        "page_size",
        "grid_axes",
        "page_grids",
        "leading_context",
        "anchor_scope",
        "parent_region_id",
        "parent_page_no",
        "context_start",
    }:
        raise ValueError("Malformed original physical continuation scope")
    size, grid = scope["page_size"], scope["grid_axes"]
    if (
        scope["kind"] != KIND
        or type(scope["version"]) is not int
        or scope["version"] != 1
        or not isinstance(scope["original_pdf_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", scope["original_pdf_sha256"])
        or type(scope["page_no"]) is not int
        or not 1 <= scope["page_no"] <= 20000
        or not isinstance(size, list)
        or len(size) != 2
        or any(type(v) not in {int, float} or not 0 < v <= 100000 for v in size)
        or not isinstance(scope["page_grids"], list)
        or not 1 <= len(scope["page_grids"]) <= 4096
    ):
        raise ValueError("Invalid original physical continuation identity")
    for observed in scope["page_grids"]:
        validate_page_grid(observed, size)
    validate_page_grid(grid, size)
    if scope["page_grids"].count(grid) != 1:
        raise ValueError("Original physical continuation has no unique observed frame")
    leading = [0, 0, size[0], grid["ys"][1]]
    validate_source_window(scope["leading_context"], leading)
    floor = scope["context_start"]
    if type(floor) not in {int, float} or not 0 <= floor <= grid["ys"][0]:
        raise ValueError("Invalid original physical continuation gap")
    left, right = column_context_band(scope)
    window = [left, floor, right, grid["ys"][0]]
    anchor, parent = scope["anchor_scope"], scope["parent_region_id"]
    if (
        not isinstance(parent, str)
        or parent
        and not re.fullmatch(r"[a-f0-9]{64}", parent)
    ):
        raise ValueError("Malformed original physical continuation parent")
    if anchor is None:
        if parent or scope["parent_page_no"] is not None or floor:
            raise ValueError("Original physical continuation has no column anchor")
        return None
    if (
        not isinstance(anchor, dict)
        or anchor.get("anchor_scope") is not None
        or anchor.get("kind") not in {None, "original_ruled_columns"}
        or anchor.get("original_pdf_sha256") != scope["original_pdf_sha256"]
        or not isinstance(anchor.get("page_size"), list)
        or len(anchor["page_size"]) != 2
        or anchor["page_size"][0] != size[0]
        or not parent
        or type(scope["parent_page_no"]) is not int
        or scope["parent_page_no"] not in {scope["page_no"], scope["page_no"] - 1}
    ):
        raise ValueError("Unproved original physical column ancestry")
    roles = original_column_roles(anchor)
    if not anchor["page_no"] <= scope["parent_page_no"] <= scope["page_no"]:
        raise ValueError("Physical column ancestry does not precede its source")
    if scope["parent_page_no"] == scope["page_no"]:
        if not floor:
            raise ValueError("Same-page physical source has no original gap")
    elif floor:
        raise ValueError("Cross-page physical source changed its original prefix")
    if roles is None or not original_columns_fit_frame(anchor, grid["xs"]):
        return None
    prefix = (
        project_source_window(scope["leading_context"], leading, window)
        if window[1] < window[3]
        else []
    )
    if not qualified_running_window(prefix, window, grid["xs"], roles["pairs"]):
        return None
    return {**roles, "xs": grid["xs"], "ys": grid["ys"][:2]}
