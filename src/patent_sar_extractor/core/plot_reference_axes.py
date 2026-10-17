"""Observed perpendicular plot strokes; numeric layout alone proves no figure."""

import math

import numpy as np

from .cell_frame_proof import inside_box
from .plot_reference_geometry import axis_bounds
from .plot_reference_pixels import observe_pixels, retained_pixels

MAX_AXIS_PIXELS = 1_000_000


def _stroke(mask, axis, bounds, dpi):
    projection = mask.sum(axis=1 if axis == "x" else 0)
    length = mask.shape[1 if axis == "x" else 0]
    indexes = np.flatnonzero(projection >= length * 0.8)
    if (
        not len(indexes)
        or np.any(np.diff(indexes) != 1)
        or (indexes[-1] - indexes[0] + 1) * 72 / dpi > 2.5
    ):
        return None
    selected = mask[indexes, :] if axis == "x" else mask[:, indexes]
    along = np.flatnonzero(selected.any(axis=0 if axis == "x" else 1))
    box = [int(along[0]), int(indexes[0]), int(along[-1]) + 1, int(indexes[-1]) + 1]
    if axis == "y":
        box = [box[1], box[0], box[3], box[2]]
    origin = [
        math.floor((bounds[0] + 1.5) * dpi / 72) * 72 / dpi,
        math.floor((bounds[1] + 1.2) * dpi / 72) * 72 / dpi,
    ]
    return [v * 72 / dpi + origin[i % 2] for i, v in enumerate(box)]


def observe_axes(page, axes, size):
    windows = axis_bounds(axes)
    if any(not inside_box(b, [0, 0, *size]) for b in windows.values()):
        return None
    result = {
        axis: observe_pixels(page, box, MAX_AXIS_PIXELS)
        for axis, box in windows.items()
    }
    return result if valid_axes(result, axes, size) else None


def valid_axes(packet, axes, size):
    if not isinstance(packet, dict) or set(packet) != {"x", "y"}:
        return False
    strokes = {}
    for axis, box in axis_bounds(axes).items():
        observed = packet[axis]
        if (
            not inside_box(box, [0, 0, *size])
            or not isinstance(observed, dict)
            or set(observed) != {"bbox", "readings"}
            or observed["bbox"] != box
            or not isinstance(observed["readings"], list)
            or len(observed["readings"]) != 2
        ):
            return False
        found = []
        for reading, dpi in zip(observed["readings"], (400, 600)):
            mask = retained_pixels(reading, box, dpi, MAX_AXIS_PIXELS)
            if mask is None:
                return False
            stroke = _stroke(mask, axis, box, dpi)
            if stroke is None:
                return False
            found.append(stroke)
        if any(abs(a - b) > 1.2 for a, b in zip(*found)):
            return False
        strokes[axis] = found[0]
    x, y = strokes["x"], strokes["y"]
    return (
        x[0] - 2.5 <= (y[0] + y[2]) / 2 <= x[2] + 2.5
        and y[1] - 2.5 <= (x[1] + x[3]) / 2 <= y[3] + 2.5
    )
