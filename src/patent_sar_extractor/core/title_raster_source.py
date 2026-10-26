"""Bounded original-pixel nominations for titles missed by both word locators."""

import cv2
import numpy as np

from .cell_header_lines import physical_row_bounds
from .cell_raster import cell_pixel_rect
from .heading_source_geometry import MAX_HEADING_HEIGHT, MAX_HEADING_ROWS
from .native_window_coverage import MAX_WINDOW_PAINTS
from .plot_reference_pixels import observe_pixels, retained_pixels
from .source_cell_pixels import MAX_CELL_PIXELS, closed_cell_masks, source_window
from .source_evidence_identity import SourceEvidenceLimit, proof_id


def observe_title_raster(page, bounds):
    """Observe complete 400dpi context; paired row reads still own all text.

    This is a locator, not a semantic/blankness acceptance certificate. No OCR,
    native-model acquisition, arbitrary resize or recognized-word crop occurs.
    """
    window = source_window(bounds, [page.rect.width, page.rect.height])
    extent = cell_pixel_rect(window, 400)
    packet = {"version": 1, "bbox": window, "pixels": None, "refusal": None}
    if extent.width * extent.height > MAX_CELL_PIXELS:
        return {**packet, "refusal": "title_raster_pixel_budget"}
    pixels = observe_pixels(page, window, MAX_CELL_PIXELS, resolutions=(400,))
    if pixels is None:
        return {**packet, "refusal": "title_raster_pixel_budget"}
    try:
        proof_id({"status": "original_title_raster", "pixels": pixels})
    except SourceEvidenceLimit:
        return {**packet, "refusal": "title_raster_evidence_budget"}
    return {**packet, "pixels": pixels}


def _remove_original_rulings(mask, extent, rulings, size):
    allowed = np.zeros_like(mask, dtype=bool)
    for ruling in rulings:
        if ruling["pixels"] is None:
            continue
        masks = closed_cell_masks(
            ruling["pixels"], ruling["cell"], size, boundary_only=True
        )
        if masks is None:
            return False
        source = cell_pixel_rect(ruling["pixels"]["bbox"], 400)
        left, top = max(source.x0, extent.x0), max(source.y0, extent.y0)
        right, bottom = min(source.x1, extent.x1), min(source.y1, extent.y1)
        if right <= left or bottom <= top:
            continue
        proved = masks[0][
            top - source.y0 : bottom - source.y0, left - source.x0 : right - source.x0
        ]
        target = allowed[
            top - extent.y0 : bottom - extent.y0, left - extent.x0 : right - extent.x0
        ]
        # Remove only the intersection with the independently retained rule.
        # Clipped raster interpolation may omit a proved pixel; it never grants
        # permission to erase an extra context pixel outside that exact mask.
        target |= proved.astype(bool)
    if allowed.any():
        _, components = cv2.connectedComponents(mask, connectivity=8)
        owners = np.unique(components[allowed & mask.astype(bool)])
        if len(owners):
            joined = np.isin(components, owners) & mask.astype(bool) & ~allowed
            # A title stroke attached to the table rule must not be cut off
            # merely because the remaining text would become easier to read.
            if joined.any():
                return False
    mask[allowed] = 0
    return True


def title_raster_marks(packet, bounds, size, rulings):
    """Re-derive every pixel row; unsupported input never returns a good prefix."""
    window = source_window(bounds, size)
    if (
        not isinstance(packet, dict)
        or set(packet) != {"version", "bbox", "pixels", "refusal"}
        or type(packet["version"]) is not int
        or packet["version"] != 1
        or packet["bbox"] != window
    ):
        return None
    extent = cell_pixel_rect(window, 400)
    over_budget = extent.width * extent.height > MAX_CELL_PIXELS
    if packet["refusal"] is not None:
        return (
            ([], packet["refusal"])
            if packet["pixels"] is None
            and (
                packet["refusal"] == "title_raster_pixel_budget"
                and over_budget
                or packet["refusal"] == "title_raster_evidence_budget"
                and not over_budget
            )
            else None
        )
    pixels = packet["pixels"]
    if (
        over_budget
        or not isinstance(pixels, dict)
        or set(pixels) != {"bbox", "readings"}
        or pixels["bbox"] != window
        or not isinstance(pixels["readings"], list)
        or len(pixels["readings"]) != 1
    ):
        return None
    try:
        proof_id({"status": "original_title_raster", "pixels": pixels})
    except (SourceEvidenceLimit, TypeError, ValueError):
        return None
    mask = retained_pixels(pixels["readings"][0], window, 400, MAX_CELL_PIXELS)
    if mask is None or not _remove_original_rulings(mask, extent, rulings, size):
        return None
    target = cell_pixel_rect(bounds, 400)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    if count - 1 > MAX_WINDOW_PAINTS:
        return [], "source_mark_budget"
    for x, y, width, height, _area in stats[1:]:
        x0, y0 = int(x) + extent.x0, int(y) + extent.y0
        x1, y1 = x0 + int(width), y0 + int(height)
        if (
            x0 < target.x1
            and x1 > target.x0
            and y0 < target.y1
            and y1 > target.y0
            and (x0 < target.x0 or y0 < target.y0 or x1 > target.x1 or y1 > target.y1)
        ):
            return [], "crossing_title_context_ink"
    inner = mask[
        target.y0 - extent.y0 : target.y1 - extent.y0,
        target.x0 - extent.x0 : target.x1 - extent.x0,
    ]
    rows, refusal = physical_row_bounds(
        inner,
        400,
        maximum_row_height=MAX_HEADING_HEIGHT,
        maximum_rows=MAX_HEADING_ROWS,
    )
    if refusal is not None:
        return [], {
            "physical_row_budget": "title_row_budget",
            "physical_row_height_budget": "title_height_budget",
        }[refusal]
    return [
        [
            (target.x0 + x0) * 72 / 400,
            (target.y0 + y0) * 72 / 400,
            (target.x0 + x1) * 72 / 400,
            (target.y0 + y1) * 72 / 400,
        ]
        for x0, y0, x1, y1 in rows
    ], None
