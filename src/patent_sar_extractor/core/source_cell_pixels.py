"""Closed original cell witnesses; conserve non-rule ink outside the text inset."""

import fitz
import numpy as np

from .cell_frame_proof import inside_box
from .cell_raster import retained_pixel_origin, valid_source_window
from .cell_rule_pixels import include_original_rule_joints, original_rule_band
from .plot_reference_pixels import observe_pixels, retained_pixels

MAX_CELL_PIXELS = 8_000_000
EMPTY_GRID_MAXIMUM_PIXELS = 4


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


def _interior(mask, cell, window, dpi, reading, *, content_only=False):
    point_origin = retained_pixel_origin(reading, window, dpi)
    ox, oy = [round(value * dpi / 72) for value in point_origin]
    origin = fitz.IRect(ox, oy, ox + mask.shape[1], oy + mask.shape[0])
    box = _relative(cell, origin, dpi)
    inner = _relative(_inset(cell), origin, dpi)
    if not inside_box(box, [0, 0, mask.shape[1], mask.shape[0]]) or not inside_box(
        inner, box
    ):
        return None
    x0, y0, x1, y1 = box
    bands = [
        original_rule_band(mask, 0, y0, x0, x1, dpi),
        original_rule_band(mask, 0, y1 - 1, x0, x1, dpi),
        original_rule_band(mask, 1, x0, y0, y1, dpi),
        original_rule_band(mask, 1, x1 - 1, y0, y1, dpi),
    ]
    if any(band is None for band in bands):
        return None
    allowed = np.zeros_like(mask, dtype=bool)
    for indices in bands[:2]:
        allowed[indices, x0:x1] = True
    for indices in bands[2:]:
        allowed[y0:y1, indices] = True
    include_original_rule_joints(mask, allowed, bands)
    if content_only:
        # Exact closed-grid rules, not a guessed margin, may be excluded for
        # the already-owned grid's blank-cell check. Every other pixel survives.
        return mask[y0:y1, x0:x1] & ~allowed[y0:y1, x0:x1]
    allowed[inner[1] : inner[3], inner[0] : inner[2]] = True
    if np.any(mask[y0:y1, x0:x1] & ~allowed[y0:y1, x0:x1]):
        return None  # No unknown glyph, sign or annotation is erased with a rule.
    reading_box = box if "source_window" in reading else inner
    return mask[reading_box[1] : reading_box[3], reading_box[0] : reading_box[2]]


def closed_cell_masks(packet, cell, size, *, content_only=False):
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
        inner = _interior(mask, cell, window, dpi, reading, content_only=content_only)
        if inner is None:
            return None
        masks.append(inner)
    return masks


def original_grid_cell_is_empty(page, cell):
    """Conservative native/unused-grid fast path; unknown rectangles are not blank."""
    if not isinstance(cell, (list, tuple)):
        return False
    cell = list(cell)
    packet = observe_closed_cell(page, cell, ink_mode="nonwhite")
    if packet is None:
        return False
    masks = closed_cell_masks(
        packet, cell, [page.rect.width, page.rect.height], content_only=True
    )
    return closed_masks_are_empty(masks)


def closed_masks_are_empty(masks):
    """The existing paired-resolution closed-grid noise bound has one owner."""
    return (
        isinstance(masks, list)
        and len(masks) == 2
        and all(int(mask.sum()) <= EMPTY_GRID_MAXIMUM_PIXELS for mask in masks)
    )


def observe_closed_cell(page, cell, *, ink_mode=None):
    size = [page.rect.width, page.rect.height]
    packet = observe_pixels(
        page,
        source_window(cell, size),
        MAX_CELL_PIXELS,
        **({"ink_mode": ink_mode} if ink_mode is not None else {}),
    )
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
    for mask, reading, dpi in zip(masks, readings, (400, 600), strict=True):
        if isinstance(reading, dict) and "source_window" in reading:
            frame = reading.get("source_frame")
            shape = frame.get("shape") if isinstance(frame, dict) else None
            window = reading["source_window"]
            if not valid_source_window(
                window, reading.get("bbox"), dpi, shape
            ) or window["source_shape"] != [*mask.shape, 3]:
                return False
            x0, y0, x1, y1 = window["read_bounds"]
            mask = mask[y0:y1, x0:x1]
        yy, xx = np.where(mask)
        expected = (
            [int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1]
            if len(xx)
            else None
        )
        if not isinstance(reading, dict) or reading.get("ink_crop_pixels") != expected:
            return False
    return True
