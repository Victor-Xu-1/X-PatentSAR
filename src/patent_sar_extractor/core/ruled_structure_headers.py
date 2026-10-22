"""Actual printed grid-header sources use the same independent cell reader."""

import re

from .activity_context_geometry import (
    context_region,
    grid_box,
    validate_context_geometry,
    validate_grid_axes,
)
from .activity_grid_role_observation import observe_role_cells
from .role_text_capture import refine_role_text
from .source_cell_tokens import cell_text
from .source_observations import source_observation_status
from .source_window_chunks import observe_window_sources
from .structure_header_context import (
    observe_header_context,
    original_header_context_role,
)
from .structure_table_headers import structure_column_pairs
from .unruled_header_readings import original_header_readings


def observe_ruled_header(page, tokens, grid, original_sha, *, grids=None):
    xs, ys = list(grid["xs"]), list(grid["ys"])
    bounds, size = [xs[0], ys[0], xs[-1], ys[1]], [page.rect.width, page.rect.height]
    sources = observe_window_sources(tokens, bounds)
    geometry = context_region(grid, [grid_box(g) for g in (grids or [grid])])[
        "context_geometry"
    ]
    reading = observe_role_cells(
        page,
        {"xs": xs, "ys": ys[:2]},
        tokens,
        retain_frames=True,
        attach_source_frames=True,
    )
    if reading is None:
        raise ValueError("Original ruled structure header exceeds its reading budget")
    refine_role_text(
        page, reading, maximum_rows=8, maximum_row_height=12, allow_chunks=False
    )
    return {
        "kind": "original_ruled_columns",
        "version": 1,
        "original_pdf_sha256": original_sha,
        "page_no": page.number + 1,
        "page_size": size,
        "grid_axes": {"xs": xs, "ys": ys},
        "context_geometry": geometry,
        "nomination": [
            cell_text(sources[0]["tokens"], [xs[c], ys[0], xs[c + 1], ys[1]])
            for c in range(len(xs) - 1)
        ],
        "source_observations": sources,
        "context_sources": observe_header_context(
            tokens, size, ys[0], geometry=geometry
        ),
        "role_cells": reading,
    }


def ruled_header_roles(scope):
    if not isinstance(scope, dict) or set(scope) != {
        "kind",
        "version",
        "original_pdf_sha256",
        "page_no",
        "page_size",
        "grid_axes",
        "context_geometry",
        "nomination",
        "source_observations",
        "context_sources",
        "role_cells",
    }:
        raise ValueError("Malformed original ruled structure-header scope")
    size, grid = scope["page_size"], scope["grid_axes"]
    if (
        scope["kind"] != "original_ruled_columns"
        or type(scope["version"]) is not int
        or scope["version"] != 1
        or type(scope["page_no"]) is not int
        or not 1 <= scope["page_no"] <= 20000
        or not isinstance(scope["original_pdf_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", scope["original_pdf_sha256"])
        or not isinstance(size, list)
        or len(size) != 2
        or any(type(v) not in {int, float} or not 0 < v <= 100000 for v in size)
        or not isinstance(grid, dict)
        or set(grid) != {"xs", "ys"}
    ):
        raise ValueError("Invalid original ruled structure-header identity")
    xs, ys = grid["xs"], grid["ys"]
    if (
        not isinstance(xs, list)
        or not isinstance(ys, list)
        or not 3 <= len(xs) <= 65
        or not 3 <= len(ys) <= 25000
    ):
        raise ValueError("Invalid original structure-header grid size")
    validate_grid_axes(grid, [xs[0], ys[0], xs[-1], ys[-1]])
    validate_context_geometry(scope["context_geometry"], grid_box(grid))
    if not 0 <= xs[0] < xs[-1] <= size[0] or not 0 <= ys[0] < ys[-1] <= size[1]:
        raise ValueError("Original structure-header grid leaves its page")
    bounds, sources = [xs[0], ys[0], xs[-1], ys[1]], scope["source_observations"]
    if (
        not isinstance(sources, list)
        or not 1 <= len(sources) <= 2
        or any(
            not isinstance(p, dict)
            or source_observation_status(p, bounds, p.get("text")) == "invalid"
            for p in sources
        )
    ):
        raise ValueError("Malformed original structure-header source")
    if [p["origin"] for p in sources] not in (["native"], ["raster", "native"]):
        raise ValueError("Foreign original structure-header source order")
    nomination = [
        cell_text(sources[0]["tokens"], [xs[c], ys[0], xs[c + 1], ys[1]])
        for c in range(len(xs) - 1)
    ]
    if scope["nomination"] != nomination:
        raise ValueError("Original ruled header nomination differs from its source")
    headers = original_header_readings(scope["role_cells"], xs, ys[:2], sources)
    role, _key = original_header_context_role(
        scope["context_sources"], ys[0], size[0], geometry=scope["context_geometry"]
    )
    if headers is None or role in {"mixed", "conflict"}:
        return None
    pairs = structure_column_pairs(headers)
    if (
        not pairs
        or any(
            not re.match(
                r"Compound|Cmpd|Cpd|Example|Ex|化合物|实施例", headers[i], re.IGNORECASE
            )
            for i, _ in pairs
        )
        and role not in {"compound", "nonfinal"}
    ):
        return None
    return {
        "headers": headers,
        "pairs": pairs,
        "xs": xs,
        "ys": ys[:2],
        "role": "nonfinal" if role == "nonfinal" else "compound",
    }
