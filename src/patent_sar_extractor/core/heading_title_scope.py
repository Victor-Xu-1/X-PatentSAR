"""Capture/replay whole original native title scope without recognizing new text."""

from .heading_cell_source import observe_cell_source
from .heading_source_geometry import MAX_HEADING_HEIGHT, heading_bounds
from .heading_title_geometry import title_scope_bounds, title_seek_bounds
from .native_window_coverage import observe_native_window
from .source_cell_pixels import observe_closed_cell
from .source_geometry import SourceTokens
from .source_observations import source_cell_observation


def _native(layout, bounds):
    return source_cell_observation(
        SourceTokens(layout.native, layout), bounds, native=True
    )


def _row(page, nomination, layout, paint_view=None):
    seek = title_seek_bounds(nomination, [page.rect.width, page.rect.height])
    return {
        "native_source": _native(layout, seek),
        "window": observe_native_window(page, seek, paint_view=paint_view),
    }


def closed_title_scope(
    page, nomination, layout, cell_source, *, row=None, paint_view=None
):
    return {
        "version": 1,
        "method": "closed_cell",
        "nomination_bbox": list(nomination),
        "page_size": [page.rect.width, page.rect.height],
        "native_seed": _native(
            layout,
            list(heading_bounds(nomination, [page.rect.width, page.rect.height])),
        ),
        "row_source": row
        if row is not None
        else _row(page, nomination, layout, paint_view),
        "cell_source": cell_source,
    }


def observe_title_scope(page, nomination, layout, *, grids=None, paint_view=None):
    """Only actual native ownership activates row expansion; OCR locators are not votes."""
    size = [page.rect.width, page.rect.height]
    seed = _native(layout, list(heading_bounds(nomination, size)))
    if not seed["tokens"] and not seed["boundary_tokens"]:
        return None
    row = _row(page, nomination, layout, paint_view)
    if grids or any(p["kind"] == "stroke-path" for p in row["window"]["paints"]):
        if not grids:
            from .table_geometry import detect_ruled_table_regions

            grids = detect_ruled_table_regions(page, dpi=240, minimum_columns=1)
        cell = observe_cell_source(page, nomination, grids, MAX_HEADING_HEIGHT)
        if cell is not None:
            return closed_title_scope(page, nomination, layout, cell, row=row)
    return {
        "version": 1,
        "method": "native_row",
        "nomination_bbox": list(nomination),
        "page_size": size,
        "native_seed": seed,
        "row_source": row,
        "cell_source": None,
    }


def replay_title_scope(page, proof, layout, *, paint_view=None):
    """Actual original rows/closed-cell pixels remain mandatory after serialization."""
    scope = proof.get("title_scope")
    nomination, size = proof["nomination"]["bbox"], proof["page_size"]
    if scope is None:
        seed = _native(layout, list(heading_bounds(nomination, size)))
        return not (seed["tokens"] or seed["boundary_tokens"])
    if title_scope_bounds(scope, nomination, size) is None or scope[
        "native_seed"
    ] != _native(layout, list(heading_bounds(nomination, size))):
        return False
    if scope["method"] == "closed_cell":
        cell = scope["cell_source"]
        if observe_closed_cell(page, cell["cell"]) != cell["pixels"]:
            return False
    return scope["row_source"] == _row(page, nomination, layout, paint_view)
