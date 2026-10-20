"""Complete original context after a caption grid, without another source read."""

from patent_sar_extractor.contracts import CAPTION_TAIL_SOURCE_VERSION

from .activity_context_geometry import MAX_TABLES, context_band, valid_box
from .caption_tail_owners import (
    caption_witness_keys,
    observe_tail_caption_cells,
    qualified_tail_source,
    validated_tail_caption_cells,
)
from .source_body_context import (
    intersecting_source_diagrams,
    original_context_extent,
    validate_page_diagrams,
)
from .source_cell_tokens import cell_lines, cell_text
from .source_observations import project_source_observation
from .source_section_roles import nonfinal_original_label
from .source_window_chunks import observe_source_window


def _window(role, size):
    left, right = context_band(role["context_geometry"])
    return [max(0, left), role["table_bbox"][3], min(size[0], right), size[1]]


def observe_caption_tail(
    page, role, regions, tokens, structures, boxes, *, captions=()
):
    if not isinstance(role, dict) or any(box is None for box in boxes):
        return None
    size = [page.rect.width, page.rect.height]
    window = _window(role, size)
    diagrams = [
        {"id": str(structure.get("id") or ""), "bbox": list(box)}
        for structure, box in zip(structures, boxes, strict=True)
    ]
    validate_page_diagrams(diagrams, size)
    chunks = observe_source_window(tokens, window) if valid_box(window) else []
    return {
        "version": CAPTION_TAIL_SOURCE_VERSION,
        "page_no": page.number + 1,
        "page_size": size,
        "window": window,
        "chunks": chunks,
        "caption_cells": observe_tail_caption_cells(captions, role, chunks),
        "page_grids": [
            [grid["xs"][0], grid["ys"][0], grid["xs"][-1], grid["ys"][-1]]
            for grid in regions
        ],
        "diagrams": diagrams,
    }


def valid_caption_tail(context, role):
    """A new/uncertain body boundary, intervening grid or diagram stops carry."""
    if not isinstance(context, dict) or set(context) != {
        "version",
        "page_no",
        "page_size",
        "window",
        "chunks",
        "page_grids",
        "diagrams",
        "caption_cells",
    }:
        return False
    try:
        size, grids = context["page_size"], context["page_grids"]
        cells = validated_tail_caption_cells(context["caption_cells"], role)
        witnesses = caption_witness_keys(cells)
        if not (
            type(context["version"]) is int
            and context["version"] == CAPTION_TAIL_SOURCE_VERSION
            and type(context["page_no"]) is int
            and context["page_no"] == role["page_no"]
            and isinstance(size, list)
            and len(size) == 2
            and valid_box([0, 0, *size])
            and isinstance(grids, list)
            and 1 <= len(grids) <= MAX_TABLES
            and all(
                valid_box(box) and box[2] <= size[0] and box[3] <= size[1]
                for box in grids
            )
            and len({tuple(box) for box in grids}) == len(grids)
            and role["table_bbox"] in grids
        ):
            return False
        window = _window(role, size)
        if context["window"] != window:
            return False
        validate_page_diagrams(context["diagrams"], size)
        if not valid_box(window):
            return window[1] == size[1] and context["chunks"] == []
        if any(
            box != role["table_bbox"]
            and box[3] > window[1]
            and min(box[2], role["table_bbox"][2]) > max(box[0], role["table_bbox"][0])
            for box in grids
        ) or intersecting_source_diagrams(context["diagrams"], window):
            return False
        extent = original_context_extent(context["chunks"], window, [])
        for chunk in context["chunks"]:
            readings = [
                project_source_observation(source, chunk["bbox"])
                for source in chunk["sources"]
            ]
            nonempty = [reading for reading in readings if reading["text"].strip()]
            if (
                any(
                    not qualified_tail_source(reading, witnesses)
                    for reading in readings
                )
                or len({" ".join(reading["text"].split()) for reading in nonempty}) > 1
            ):
                return False
            if any(
                nonfinal_original_label(cell_text(line, chunk["bbox"]))
                for reading in nonempty
                for line in cell_lines(reading["tokens"], chunk["bbox"])
            ):
                return False
        return (
            extent["body_bottom"] == size[1]
            and extent["trusted_bottom"] == size[1]
            and not extent["unproved_boundaries"]
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
