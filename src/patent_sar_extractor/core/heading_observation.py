"""One bounded native/raster heading observer using the existing text-cell SDK."""

import fitz

from .heading_cell_source import observe_cell_source
from .heading_source_geometry import (
    MAX_HEADING_HEIGHT,
    MAX_HEADING_ROWS,
    heading_bounds,
)
from .heading_source_proof import heading_observation_status
from .heading_title_geometry import title_scope_bounds
from .heading_title_scope import closed_title_scope, observe_title_scope
from .native_window_coverage import native_window_complete, observe_native_window
from .page_ocr_cache import get_ocr_engine
from .paired_text_observation import observe_paired_text
from .source_geometry import SourceTokens, overlaps, source_layout
from .source_observations import source_cell_observation, source_observation_status
from .source_paint_visibility import visible_native_tokens
from .source_section_roles import section_heading


def observe_heading(
    page,
    line,
    original_pdf_sha256,
    *,
    layout=None,
    grids=None,
    paint_view=None,
    column_sources=(),
):
    bounds = heading_bounds(line["bbox"], [page.rect.width, page.rect.height])
    if bounds.is_empty or bounds.height > MAX_HEADING_HEIGHT:
        raise ValueError("Original heading exceeds its physical source bounds")
    layout = layout if layout is not None else source_layout(page)
    scope = observe_title_scope(
        page,
        line["bbox"],
        layout,
        grids=grids,
        paint_view=paint_view,
        column_sources=column_sources,
        original_pdf_sha256=original_pdf_sha256,
    )
    scoped = (
        title_scope_bounds(scope, line["bbox"], [page.rect.width, page.rect.height])
        if scope is not None
        else None
    )
    if scope is not None and scoped is None:
        raise ValueError("Original title scope could not be validated")
    if scoped is not None:
        bounds = fitz.Rect(scoped[0])
    native = source_cell_observation(
        SourceTokens(layout.native, layout), tuple(bounds), native=True
    )
    proof = {
        "version": 1,
        "original_pdf_sha256": original_pdf_sha256,
        "page_no": page.number + 1,
        "page_size": [page.rect.width, page.rect.height],
        "bbox": list(bounds),
        "nomination": {
            "text": line["text"],
            "source": line["source"],
            "bbox": list(line["bbox"]),
            "geometry_space": line.get("geometry_space", "locator"),
            **({"rows": line["heading_rows"]} if "heading_rows" in line else {}),
        },
        "native_source": native,
        "native_window": observe_native_window(
            page, list(bounds), paint_view=paint_view
        ),
        "raster_bounds": list(layout.raster_bounds) if layout.raster_bounds else None,
        "observations": [],
        "rendered_frames": [],
        **({"title_scope": scope} if scope is not None else {}),
    }
    # Resolve the physical source before OCR. Reading an arbitrary locator's
    # padded rectangle first can turn a ruling stroke into a spurious digit.
    # The original native window remains retained, never promoted by geometry.
    proof["status"], _ = heading_observation_status(proof)
    if scoped is not None:
        if scoped[1] is None:
            _observe_window(page, proof, layout, paint_view=paint_view)
        return proof
    if proof["status"] != "unresolved":
        return proof
    if grids is None:
        from .table_geometry import detect_ruled_table_regions

        grids = detect_ruled_table_regions(page, dpi=240, minimum_columns=1)
    cell_source = observe_cell_source(page, line["bbox"], grids, MAX_HEADING_HEIGHT)
    if cell_source is None:
        _observe_window(page, proof, layout, paint_view=paint_view)
        return proof
    candidate = {
        **proof,
        "version": 2,
        "bbox": cell_source["cell"],
        "native_source": source_cell_observation(
            SourceTokens(layout.native, layout), tuple(cell_source["cell"]), native=True
        ),
        "native_window": observe_native_window(page, cell_source["cell"]),
        "original_heading": proof,
        "cell_source": cell_source,
        "observations": [],
        "rendered_frames": [],
    }
    if (
        candidate["native_source"]["tokens"]
        or candidate["native_source"]["boundary_tokens"]
    ):
        candidate["title_scope"] = closed_title_scope(
            page, line["bbox"], layout, cell_source
        )
    _observe_window(page, candidate, layout, paint_view=paint_view)
    return candidate


def _observe_window(page, proof, layout, *, paint_view=None):
    bounds = fitz.Rect(proof["bbox"])
    native = proof["native_source"]
    if native["text"].strip() and (
        source_observation_status(native, proof["bbox"], native["text"]) != "qualified"
        or not visible_native_tokens(page, native, paint_view=paint_view)
    ):
        proof["status"] = "unresolved"
        return  # Retained unreadable/conflicting native claims cannot be outvoted.
    status, _ = heading_observation_status(proof)
    raster = layout.raster_bounds is not None and overlaps(layout.raster_bounds, bounds)
    if status != "confirmed" and (
        raster
        or not native["text"].strip()
        or not native_window_complete(proof["native_window"], native)
    ):
        engine = get_ocr_engine()
        if engine and engine[0] == "rapidocr":
            proof["observations"], proof["rendered_frames"] = observe_paired_text(
                page,
                bounds,
                engine[1],
                lambda raw, _kind: raw if section_heading(raw) else "",
                maximum_rows=MAX_HEADING_ROWS,
                maximum_row_height=MAX_HEADING_HEIGHT,
            )
    proof["status"], _ = heading_observation_status(proof)
    if proof["status"] == "unresolved" and len(proof["observations"]) == 2:
        from .text_ocr.source_capture import refine_source_text

        proof["observations"] = refine_source_text(
            page,
            bounds,
            proof["observations"],
            maximum_rows=MAX_HEADING_ROWS,
            maximum_row_height=MAX_HEADING_HEIGHT,
        )
        proof["status"], _ = heading_observation_status(proof)
