"""Retained compact graphic-key pixels, observed with the sole cell renderer."""

import numpy as np

from .cell_frame_proof import inside_box
from .plot_reference_geometry import marker_bounds
from .plot_reference_pixels import observe_pixels, retained_pixels

MAX_MARKER_PIXELS = 50000


def marker_extent(mask, dpi, heading_height):
    y, x = np.nonzero(mask)
    if not len(x):
        return None
    box = [int(x.min()), int(y.min()), int(x.max()) + 1, int(y.max()) + 1]
    width, height = box[2] - box[0], box[3] - box[1]
    if not (
        width * 72 / dpi >= 4
        and height * 72 / dpi <= max(5, heading_height * 0.55)
        and width >= height * 1.8
        and mask[box[1] : box[3], box[0] : box[2]].sum(axis=1).max() >= width * 0.35
    ):
        return None
    return [v * 72 / dpi for v in box]


def observe_marker(page, label, size):
    bounds = marker_bounds(label, size)
    if not inside_box(bounds, [0, 0, *size]):
        return None
    result = observe_pixels(page, bounds, MAX_MARKER_PIXELS)
    return result if valid_marker(result, label, size) else None


def valid_marker(packet, label, size):
    if not isinstance(packet, dict) or set(packet) != {"bbox", "readings"}:
        return False
    bounds, readings = packet["bbox"], packet["readings"]
    if (
        bounds != marker_bounds(label, size)
        or not inside_box(bounds, [0, 0, *size])
        or not isinstance(readings, list)
        or len(readings) != 2
    ):
        return False
    extents = []
    for reading, dpi in zip(readings, (400, 600)):
        mask = retained_pixels(reading, bounds, dpi, MAX_MARKER_PIXELS)
        if mask is None:
            return False
        extent = marker_extent(mask, dpi, label[3] - label[1])
        if extent is None:
            return False
        extents.append(extent)
    return all(abs(a - b) <= 1.2 for a, b in zip(*extents))
