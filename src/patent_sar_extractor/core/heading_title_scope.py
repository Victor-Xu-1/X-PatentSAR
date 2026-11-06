"""Capture/replay whole original native title scope without recognizing new text."""

from .heading_cell_source import observe_cell_source
from .heading_source_geometry import MAX_HEADING_HEIGHT, heading_bounds
from .heading_title_columns import title_column_windows
from .heading_title_geometry import title_scope_bounds, title_seek_bounds
from .native_window_coverage import observe_native_window
from .source_cell_pixels import observe_closed_cell
from .source_evidence_identity import SourceEvidenceLimit, proof_id
from .source_geometry import SourceTokens
from .source_observations import source_cell_observation


def _bounded_panel_scope(scope):
    """Never persist an oversized original panel as a valid title witness."""
    try:
        proof_id({"status": "original_title_panel", "scope": scope})
    except SourceEvidenceLimit:
        return False
    return True


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


def observe_title_scope(
    page,
    nomination,
    layout,
    *,
    grids=None,
    paint_view=None,
    column_sources=(),
    original_pdf_sha256=None,
    raster_nomination=False,
):
    """Whole physical native/raster scope; recognized locators grant no role."""
    size = [page.rect.width, page.rect.height]
    seed = _native(layout, list(heading_bounds(nomination, size)))
    if not seed["tokens"] and not seed["boundary_tokens"]:
        if (
            raster_nomination
            and layout.raster_bounds is not None
            and (
                not grids
                or observe_cell_source(page, nomination, grids, MAX_HEADING_HEIGHT)
                is None
            )
        ):
            from .heading_raster_scope import observe_raster_scope, raster_scope_bounds

            scope = observe_raster_scope(page, nomination)
            owned = raster_scope_bounds(scope, nomination, size)
            if owned is not None and owned[1] is not None and grids:
                from .heading_panel_scope import observe_panel

                heading = {"page_size": size, "nomination": {"bbox": list(nomination)}}
                panel = observe_panel(page, heading, grids)
                if panel is not None:
                    panel_scope = {
                        "version": 5,
                        "method": "panel_raster_row",
                        "nomination_bbox": list(nomination),
                        "page_size": size,
                        "panel": panel,
                    }
                    bounded = title_scope_bounds(panel_scope, nomination, size)
                    if (
                        bounded is not None
                        and bounded[1] is None
                        and _bounded_panel_scope(panel_scope)
                    ):
                        return panel_scope
            if owned is not None and owned[1] is not None and column_sources:
                columns = {
                    **scope,
                    "version": 6,
                    "method": "raster_column_row",
                    "column_sources": list(column_sources),
                    "original_pdf_sha256": original_pdf_sha256,
                    "page_no": page.number + 1,
                }
                bounded = title_scope_bounds(columns, nomination, size)
                if bounded is not None and bounded[1] is None:
                    return columns
            # A physical rule keeps the existing whole-cell authority. The
            # ordinary-row reader cannot replace its ink-conservation witness.
            if owned is not None and owned[1] == "original_title_requires_cell":
                return None
            return scope
        return None
    row = _row(page, nomination, layout, paint_view)
    if grids or any(p["kind"] == "stroke-path" for p in row["window"]["paints"]):
        if not grids:
            from .table_geometry import detect_ruled_table_regions

            grids = detect_ruled_table_regions(page, dpi=240, minimum_columns=1)
        cell = observe_cell_source(page, nomination, grids, MAX_HEADING_HEIGHT)
        if cell is not None:
            return closed_title_scope(page, nomination, layout, cell, row=row)
    scope = {
        "version": 1,
        "method": "native_row",
        "nomination_bbox": list(nomination),
        "page_size": size,
        "native_seed": seed,
        "row_source": row,
        "cell_source": None,
    }
    ordinary = title_scope_bounds(scope, nomination, size)
    if ordinary is not None and ordinary[1] is not None and grids:
        from .heading_panel_scope import observe_panel

        heading = {"page_size": size, "nomination": {"bbox": list(nomination)}}
        panel = observe_panel(page, heading, grids)
        if panel is not None:
            panel_scope = {**scope, "version": 4, "method": "panel_row", "panel": panel}
            bounded = title_scope_bounds(panel_scope, nomination, size)
            if (
                bounded is not None
                and bounded[1] is None
                and _bounded_panel_scope(panel_scope)
            ):
                return panel_scope
    if not column_sources or ordinary is None or ordinary[1] is None:
        return scope  # An already-complete ordinary row needs no column replay.
    columns = list(column_sources)
    owned = title_column_windows(
        columns,
        page.number + 1,
        size,
        original_pdf_sha256,
        nomination,
        title_seek_bounds(nomination, size),
    )
    return (
        {
            **scope,
            "version": 2,
            "column_sources": columns,
            "original_pdf_sha256": original_pdf_sha256,
            "page_no": page.number + 1,
        }
        if owned
        else scope
    )


def replay_title_scope(page, proof, layout, *, paint_view=None):
    """Actual original rows/closed-cell pixels remain mandatory after serialization."""
    scope = proof.get("title_scope")
    nomination, size = proof["nomination"]["bbox"], proof["page_size"]
    if isinstance(scope, dict) and scope.get("version") == 5:
        from .heading_panel_raster_scope import replay_panel_raster

        seed = _native(layout, list(heading_bounds(nomination, size)))
        if seed["tokens"] or seed["boundary_tokens"]:
            return False
        try:
            replay_panel_raster(page, scope)
        except (ValueError, TypeError, KeyError, IndexError):
            return False
        return title_scope_bounds(scope, nomination, size) is not None
    if isinstance(scope, dict) and scope.get("version") == 6:
        from .heading_page_replay import HeadingPageReplay
        from .heading_raster_scope import observe_raster_scope
        from .source_document import document_sha256

        seed = _native(layout, list(heading_bounds(nomination, size)))
        if seed["tokens"] or seed["boundary_tokens"]:
            return False
        if scope["original_pdf_sha256"] != document_sha256(page.parent):
            return False
        base = {key: scope[key] for key in ("nomination_bbox", "page_size", "pixels")}
        base.update(version=3, method="raster_row")
        if base != observe_raster_scope(page, nomination):
            return False
        replay = HeadingPageReplay(page.parent)
        for section in scope["column_sources"]:
            replay.column_source(section)
        return title_scope_bounds(scope, nomination, size) is not None
    if isinstance(scope, dict) and scope.get("version") == 3:
        from .heading_raster_scope import replay_raster_scope

        seed = _native(layout, list(heading_bounds(nomination, size)))
        return not (seed["tokens"] or seed["boundary_tokens"]) and replay_raster_scope(
            page, scope
        )
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
    if scope.get("version") == 4:
        from .heading_panel_scope import replay_panel

        heading = {"page_size": size, "nomination": {"bbox": list(nomination)}}
        try:
            replay_panel(page, scope["panel"], heading)
        except (ValueError, TypeError, KeyError, IndexError):
            return False
    if scope["version"] == 2:
        from .heading_page_replay import HeadingPageReplay
        from .source_document import document_sha256

        if scope["original_pdf_sha256"] != document_sha256(page.parent):
            return False
        replay = HeadingPageReplay(page.parent)
        for section in scope["column_sources"]:
            replay.column_source(section)
    return scope["row_source"] == _row(page, nomination, layout, paint_view)
