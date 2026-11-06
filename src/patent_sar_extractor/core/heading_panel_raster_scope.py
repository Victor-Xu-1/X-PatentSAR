"""Original closed-panel pixels bound a raster title without erasing its ink."""

import math

import fitz
import numpy as np

from .cell_frame_proof import inside_box
from .cell_header_lines import physical_row_bounds
from .cell_raster import cell_pixel_rect, retained_pixel_origin
from .cell_rule_pixels import original_rule_band
from .heading_panel_scope import panel_bounds, replay_panel
from .heading_raster_scope import _selected_rows
from .heading_source_geometry import MAX_HEADING_HEIGHT, heading_bounds
from .plot_reference_pixels import retained_pixels
from .source_cell_pixels import MAX_CELL_PIXELS, _inset, _relative, closed_cell_masks

MARGIN = 16


def _safe_title_edges(pixels, cell, size, nomination):
    """No unclassified original ink at either panel edge near this title row."""
    boundary = closed_cell_masks(pixels, cell, size, boundary_only=True)
    if boundary is None:
        return False
    for reading, rules, dpi in zip(
        pixels["readings"], boundary, (400, 600), strict=True
    ):
        mask = retained_pixels(reading, pixels["bbox"], dpi, MAX_CELL_PIXELS)
        if mask is None or rules.shape != mask.shape:
            return False
        ox, oy = [
            round(value * dpi / 72)
            for value in retained_pixel_origin(reading, pixels["bbox"], dpi)
        ]
        origin = fitz.IRect(ox, oy, ox + mask.shape[1], oy + mask.shape[0])
        box, inner = _relative(cell, origin, dpi), _relative(_inset(cell), origin, dpi)
        if not inside_box(inner, box) or not inside_box(
            box, [0, 0, mask.shape[1], mask.shape[0]]
        ):
            return False
        y0 = max(box[1], int((nomination[1] - MARGIN) * dpi / 72) - oy)
        y1 = min(box[3], int((nomination[3] + MARGIN) * dpi / 72) - oy + 1)
        if y0 >= y1:
            return False
        unknown = mask[y0:y1, box[0] : box[2]] & ~rules[y0:y1, box[0] : box[2]]
        left, right = inner[0] - box[0], inner[2] - box[0]
        top = min(y1 - y0, max(0, inner[1] - y0))
        bottom = max(0, min(y1 - y0, inner[3] - y0))
        if (
            np.any(unknown[:, :left])
            or np.any(unknown[:, right:])
            or np.any(unknown[:top, :])
            or np.any(unknown[bottom:, :])
        ):
            return False
    return True


def panel_raster_bounds(packet, nomination, size):
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(
            type(v) not in {int, float} or not math.isfinite(v) or v <= 0 for v in size
        )
        or not isinstance(nomination, list)
        or not isinstance(packet, dict)
        or set(packet) != {"version", "method", "nomination_bbox", "page_size", "panel"}
        or type(packet["version"]) is not int
        or packet["version"] != 5
        or packet["method"] != "panel_raster_row"
        or packet["nomination_bbox"] != list(nomination)
        or packet["page_size"] != size
        or not inside_box(nomination, [0, 0, *size])
    ):
        return None
    heading = {"page_size": size, "nomination": {"bbox": list(nomination)}}
    try:
        cell = panel_bounds(packet["panel"], heading)
        if cell is None or not _safe_title_edges(
            packet["panel"]["pixels"], cell, size, nomination
        ):
            return list(
                heading_bounds(nomination, size)
            ), "unproved_original_title_panel"
        masks = closed_cell_masks(
            packet["panel"]["pixels"], cell, size, content_only=True
        )
    except (ValueError, TypeError, KeyError, IndexError):
        return None
    if masks is None:
        return None
    extent = cell_pixel_rect(cell, 400)
    local = [
        cell[0],
        max(cell[1], nomination[1] - MARGIN),
        cell[2],
        min(cell[3], nomination[3] + MARGIN),
    ]
    crop = cell_pixel_rect(local, 400)
    y0, y1 = crop.y0 - extent.y0, crop.y1 - extent.y0
    mask = masks[0][y0:y1, :]
    if mask.size == 0 or y0 < 0 or y1 > masks[0].shape[0]:
        return None
    rows, refusal = physical_row_bounds(
        mask, 400, maximum_row_height=MAX_HEADING_HEIGHT, maximum_rows=32
    )
    fallback = list(heading_bounds(nomination, size))
    if refusal is not None:
        return fallback, refusal
    original = [
        [
            (extent.x0 + row[0]) * 72 / 400,
            (crop.y0 + row[1]) * 72 / 400,
            (extent.x0 + row[2]) * 72 / 400,
            (crop.y0 + row[3]) * 72 / 400,
        ]
        for row in rows
    ]
    selected = _selected_rows(original, nomination)
    if not selected or selected != list(range(selected[0], selected[-1] + 1)):
        return fallback, "ambiguous_original_title_rows"
    first, last = selected[0], selected[-1]
    if rows[first][1] <= 0 or rows[last][3] >= mask.shape[0]:
        return fallback, "crossing_original_title_rows"
    for index in selected:
        row = rows[index]
        for y in range(row[1], row[3]):
            if original_rule_band(mask[y : y + 1], 0, 0, row[0], row[2], 400):
                return fallback, "original_title_requires_cell"
    top = max(local[1], original[first - 1][3] if first else local[1])
    bottom = min(local[3], original[last + 1][1] if last + 1 < len(rows) else local[3])
    bounds = [
        max(cell[0], min(original[i][0] for i in selected) - 2),
        original[first][1] - min(1.5, (original[first][1] - top) / 2),
        min(cell[2], max(original[i][2] for i in selected) + 2),
        original[last][3] + min(1.5, (bottom - original[last][3]) / 2),
    ]
    if bounds[3] - bounds[1] > MAX_HEADING_HEIGHT or not inside_box(bounds, cell):
        return fallback, "title_height_budget"
    return bounds, None


def replay_panel_raster(page, packet):
    heading = {
        "page_size": packet["page_size"],
        "nomination": {"bbox": packet["nomination_bbox"]},
    }
    replay_panel(page, packet["panel"], heading)
