"""Closed original cell witnesses; conserve non-rule ink outside the text inset."""

import math

import fitz
import numpy as np

from .cell_frame_proof import inside_box
from .plot_reference_pixels import observe_pixels, retained_pixels
from .table_geometry import RULE_GAP_PT

MAX_CELL_PIXELS = 8_000_000


def source_window(cell, size):
    return [
        max(0, cell[0] - 3),
        max(0, cell[1] - 3),
        min(size[0], cell[2] + 3),
        min(size[1], cell[3] + 3),
    ]


def _pixels(box, dpi):
    return (fitz.Rect(box) * fitz.Matrix(dpi / 72, dpi / 72)).irect


def _inset(box):
    return [box[0] + 1.5, box[1] + 1.2, box[2] - 1.5, box[3] - 1.2]


def _relative(box, origin, dpi):
    rectangle = _pixels(box, dpi)
    return [
        rectangle.x0 - origin.x0,
        rectangle.y0 - origin.y0,
        rectangle.x1 - origin.x0,
        rectangle.y1 - origin.y0,
    ]


def _band(mask, axis, position, lo, hi, dpi):
    extent = mask.shape[axis]
    margin = math.ceil(2.5 * dpi / 72)
    start, end = (
        max(0, math.floor(position) - margin),
        min(extent, math.ceil(position) + margin + 1),
    )
    strip = mask[start:end, lo:hi] if axis == 0 else mask[lo:hi, start:end].T
    if not strip.size:
        return None
    # Match the detector's physical gap policy at this render's pixel phase.
    # Do not paint in gaps or discard fringe pixels with a mean-coverage cutoff.
    maximum_gap = math.ceil(RULE_GAP_PT * dpi / 72)
    indices = []
    for index, line in enumerate(strip):
        occupied = np.flatnonzero(line)
        if (
            len(occupied)
            and max(
                int(occupied[0]),
                int(line.size - occupied[-1] - 1),
                int(np.diff(occupied).max()) - 1 if len(occupied) > 1 else 0,
            )
            <= maximum_gap
        ):
            indices.append(start + index)
    if not indices or (indices[-1] - indices[0] + 1) * 72 / dpi > 2.5:
        return None
    return indices


def _interior(mask, cell, window, dpi):
    origin = _pixels(_inset(window), dpi)
    box = _relative(cell, origin, dpi)
    inner = _relative(_inset(cell), origin, dpi)
    if not inside_box(box, [0, 0, mask.shape[1], mask.shape[0]]) or not inside_box(
        inner, box
    ):
        return None
    x0, y0, x1, y1 = box
    bands = [
        _band(mask, 0, y0, x0, x1, dpi),
        _band(mask, 0, y1 - 1, x0, x1, dpi),
        _band(mask, 1, x0, y0, y1, dpi),
        _band(mask, 1, x1 - 1, y0, y1, dpi),
    ]
    if any(band is None for band in bands):
        return None
    allowed = np.zeros_like(mask, dtype=bool)
    allowed[inner[1] : inner[3], inner[0] : inner[2]] = True
    for indices in bands[:2]:
        allowed[indices, x0:x1] = True
    for indices in bands[2:]:
        allowed[y0:y1, indices] = True
    _rule_joints(mask, allowed, bands)
    if np.any(mask[y0:y1, x0:x1] & ~allowed[y0:y1, x0:x1]):
        return None  # No unknown glyph, sign or annotation is erased with a rule.
    return mask[inner[1] : inner[3], inner[0] : inner[2]]


def _rule_joints(mask, allowed, bands):
    """Keep an original one-pixel corner join of two independently proved rules.

    Rasterized miter corners can extend diagonally beyond both axial strips.
    A pixel qualifies only beside actual dark ink in each original rule, never
    by dilating an edge or filling a gap. Other inset ink remains unexplained.
    """
    for horizontal in bands[:2]:
        rows = set(horizontal)
        for vertical in bands[2:]:
            columns = set(vertical)
            for y in range(max(0, min(rows) - 1), min(mask.shape[0], max(rows) + 2)):
                for x in range(
                    max(0, min(columns) - 1), min(mask.shape[1], max(columns) + 2)
                ):
                    if (
                        mask[y, x]
                        and any(
                            other in rows and mask[other, x] for other in (y - 1, y + 1)
                        )
                        and any(
                            other in columns and mask[y, other]
                            for other in (x - 1, x + 1)
                        )
                    ):
                        allowed[y, x] = True


def closed_cell_masks(packet, cell, size):
    if (
        not inside_box(cell, [0, 0, *size])
        or not isinstance(packet, dict)
        or set(packet) != {"bbox", "readings"}
    ):
        return None
    window = source_window(cell, size)
    if (
        packet["bbox"] != window
        or not isinstance(packet["readings"], list)
        or len(packet["readings"]) != 2
    ):
        return None
    masks = []
    for reading, dpi in zip(packet["readings"], (400, 600)):
        mask = retained_pixels(reading, window, dpi, MAX_CELL_PIXELS)
        if mask is None:
            return None
        inner = _interior(mask, cell, window, dpi)
        if inner is None:
            return None
        masks.append(inner)
    return masks


def observe_closed_cell(page, cell):
    size = [page.rect.width, page.rect.height]
    packet = observe_pixels(page, source_window(cell, size), MAX_CELL_PIXELS)
    return (
        packet
        if packet is not None and closed_cell_masks(packet, cell, size) is not None
        else None
    )


def cell_readings_conserve_ink(masks, readings):
    """Use this replay's already bounded masks, not a second decompression pass."""
    if (
        not isinstance(masks, list)
        or len(masks) != 2
        or not isinstance(readings, list)
        or len(readings) != 2
    ):
        return False
    for mask, reading in zip(masks, readings):
        yy, xx = np.where(mask)
        expected = (
            [int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1]
            if len(xx)
            else None
        )
        if not isinstance(reading, dict) or reading.get("ink_crop_pixels") != expected:
            return False
    return True
