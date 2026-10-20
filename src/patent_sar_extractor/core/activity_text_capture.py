"""Attach physical source to the sole declared-text parser, preserving raw text."""

from patent_sar_extractor.contracts import DECLARED_TEXT_SOURCE_VERSION

from .activity_text_sources import MAX_TEXT_SOURCE_LINES, same_text, text_line_qualified
from .cell_frame_proof import inside_box
from .cell_raster import render_cell_raster
from .cell_text_chunks import observe_text_cell
from .native_cell_replay import original_native_cell_matches
from .page_ocr_cache import get_ocr_engine
from .source_geometry import (
    SourceTokens,
    native_cell_text,
    native_region,
    source_layout,
)
from .source_observations import source_cell_observation
from .source_page_lines import native_page_lines
from .source_paint_visibility import native_paint_view
from .table_cells import CellRenderLimit
from .text_ocr.source_capture import refine_source_text


def _line_readings(page, bounds, tokens, layout, paints):
    native = native_region(tokens, bounds, False)
    observation = {
        "method": "native_cell",
        "text": native_cell_text(tokens, bounds),
        "bbox": list(bounds),
        "source_observation": source_cell_observation(tokens, bounds, native=True),
    }
    if native:
        if not original_native_cell_matches(
            page, observation, layout=layout, paint_view=paints
        ):
            observation["capture_error"] = "unproved_original_native_text"
        return [observation]
    readings = []
    if observation["text"]:
        readings.append({**observation, "native_role": "witness"})
    engine = get_ocr_engine()
    if not engine or engine[0] != "rapidocr":
        return readings
    for dpi in (400, 600):
        try:
            raster = render_cell_raster(page, bounds, dpi, purpose="text")
        except CellRenderLimit:
            return readings
        reading = observe_text_cell(
            raster.image, dpi, engine[1], rows_per_chunk=8
        ).evidence(dpi, bounds)
        reading.update(source_frame=raster.frame, source_window=raster.source_window)
        readings.append(reading)
    # Reuse the same unresolved-only paired recovery as ordinary physical cells.
    # The independent native layer remains a contradiction witness, not a vote.
    primary = [r for r in readings if r.get("native_role") != "witness"]
    return list(refine_source_text(page, bounds, primary, maximum_rows=8)) + [
        r for r in readings if r.get("native_role") == "witness"
    ]


def capture_text_page(page, text, cached_lines=()):
    """Raw cache lines nominate locations only; current reads must prove text.

    Native source order follows original extraction order, not guessed columns.
    Scanned/mixed source coordinates remain the shared page observer's proposals.
    Only agreeing qualified current physical reads supply the new parser's text;
    cache nominations stay raw and cannot vote over the original source.
    Missing/changed/over-bound sources retain empty/partial reads and refuse.
    """
    layout = source_layout(page)
    native = layout.raster_bounds is None and same_text(page.get_text("text"), text)
    proposals = native_page_lines(layout) if native else cached_lines
    proof = {
        "version": DECLARED_TEXT_SOURCE_VERSION,
        "origin": "native" if native else "located",
        "nomination_text": text,
        "page_size": [page.rect.width, page.rect.height],
        "lines": [],
    }
    if (
        not isinstance(proposals, (list, tuple))
        or len(proposals) > MAX_TEXT_SOURCE_LINES
    ):
        return proof
    tokens = SourceTokens(layout.native, layout, layout.raster_bounds)
    paints = native_paint_view(page)
    for line in proposals:
        if (
            not isinstance(line, dict)
            or not isinstance(line.get("text"), str)
            or not line["text"].strip()
            or len(line["text"]) > 4096
            or not inside_box(line.get("bbox"), [0, 0, *proof["page_size"]])
        ):
            return proof
        bounds = list(line["bbox"])
        readings = _line_readings(page, bounds, tokens, layout, paints)
        # No character/value inference: only an independently qualified reading
        # pair may replace a low-resolution location nomination in new derived
        # text. Original cache and every differing read remain unchanged.
        candidate = next(
            (r["text"] for r in readings if r.get("native_role") != "witness"),
            line["text"],
        )
        current = {
            "nomination": line["text"],
            "text": line["text"],
            "bbox": bounds,
            "observations": readings,
        }
        selected = {**current, "text": candidate}
        proof["lines"].append(selected if text_line_qualified(selected) else current)
    return proof
