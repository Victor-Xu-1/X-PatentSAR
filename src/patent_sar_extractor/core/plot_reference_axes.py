"""Observed perpendicular plot strokes; numeric layout alone proves no figure."""

import numpy as np

from .cell_frame_proof import inside_box
from .cell_raster import retained_pixel_origin
from .plot_reference_geometry import AXIS_MARGIN, axis_bounds
from .plot_reference_pixels import observe_pixels, retained_pixels

MAX_AXIS_PIXELS = 1_000_000


def _stroke(mask, axis, bounds, dpi, reading):
    projection = mask.sum(axis=1 if axis == "x" else 0)
    length = mask.shape[1 if axis == "x" else 0]
    if "source_window" in reading:
        # MuPDF rounds the device frame outward. Its fractional outer padding
        # is not extra original axis length. Keep the same 80% physical rule;
        # historical unmarked masks retain their historical device denominator.
        coordinate = 0 if axis == "x" else 1
        length = (bounds[coordinate + 2] - bounds[coordinate]) * dpi / 72
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
    origin = retained_pixel_origin(reading, bounds, dpi)
    return [v * 72 / dpi + origin[i % 2] for i, v in enumerate(box)]


def _windows(axes, size, anchor):
    windows = axis_bounds(axes)
    if anchor is not None:
        if not isinstance(anchor, dict) or set(anchor) != {"axes", "pixels"}:
            return None
        # The source is the already-owned original nomination, not another
        # successful window search. Its base packet cannot contain an anchor.
        original = axis_strokes(
            anchor["pixels"],
            anchor["axes"],
            size,
            nomination=isinstance(anchor["pixels"], dict)
            and "nominal_dpi" in anchor["pixels"],
        )
        if original is None:
            return None
        stroke = original["x"]
        window = windows["x"]
        top, bottom = (
            max(window[1], stroke[1] - AXIS_MARGIN),
            min(window[3], stroke[3] + AXIS_MARGIN),
        )
        if not top <= stroke[1] < stroke[3] <= bottom:
            return None
        windows["x"] = [window[0], top, window[2], bottom]
    if any(not inside_box(b, [0, 0, *size]) for b in windows.values()):
        return None
    return windows


def observe_axes(page, axes, size, *, anchor=None, nomination=False):
    windows = _windows(axes, size, anchor)
    if windows is None:
        return None
    result = {
        axis: observe_pixels(
            page, box, MAX_AXIS_PIXELS, resolutions=(400,) if nomination else (400, 600)
        )
        for axis, box in windows.items()
    }
    if nomination:
        result["nominal_dpi"] = 400
    return (
        result
        if axis_strokes(result, axes, size, anchor=anchor, nomination=nomination)
        is not None
        else None
    )


def axis_strokes(packet, axes, size, *, anchor=None, nomination=False):
    if not isinstance(packet, dict) or set(packet) != (
        {"x", "y"} | ({"nominal_dpi"} if nomination else set())
    ):
        return None
    if nomination and (
        type(packet["nominal_dpi"]) is not int or packet["nominal_dpi"] != 400
    ):
        return None
    windows = _windows(axes, size, anchor)
    if windows is None:
        return None
    strokes = {}
    for axis, box in windows.items():
        observed = packet[axis]
        if (
            not inside_box(box, [0, 0, *size])
            or not isinstance(observed, dict)
            or set(observed) != {"bbox", "readings"}
            or observed["bbox"] != box
            or not isinstance(observed["readings"], list)
            or len(observed["readings"]) != (1 if nomination else 2)
        ):
            return None
        found = []
        for reading, dpi in zip(
            observed["readings"], (400,) if nomination else (400, 600)
        ):
            mask = retained_pixels(reading, box, dpi, MAX_AXIS_PIXELS)
            if mask is None:
                return None
            stroke = _stroke(mask, axis, box, dpi, reading)
            if stroke is None:
                return None
            found.append(stroke)
        if len(found) == 2 and any(abs(a - b) > 1.2 for a, b in zip(*found)):
            return None
        strokes[axis] = found[0]
    x, y = strokes["x"], strokes["y"]
    return (
        strokes
        if (
            x[0] - 2.5 <= (y[0] + y[2]) / 2 <= x[2] + 2.5
            and y[1] - 2.5 <= (x[1] + x[3]) / 2 <= y[3] + 2.5
        )
        else None
    )


def valid_axes(packet, axes, size, *, anchor=None):
    return axis_strokes(packet, axes, size, anchor=anchor) is not None


def axis_word_window(packet, axes, caption, size):
    """Complete page-width original strip, below the axis and above its caption.

    Word detections cannot define the first/last retained ink. Unsupported or
    overlapping layouts refuse rather than accepting only the detected prefix.
    """
    strokes = axis_strokes(packet, axes, size)
    if strokes is None:
        return None
    top, bottom = strokes["x"][3] + 0.5, caption["bbox"][1]
    bounds = [0, top, size[0], bottom]
    return (
        bounds
        if 0 < bottom - top <= 128 and inside_box(bounds, [0, 0, *size])
        else None
    )


def complete_axis_windows(packet, axes, caption, size):
    """Both full source strips from observed strokes, never detected tick ends."""
    strokes = axis_strokes(packet, axes, size, nomination=True)
    if strokes is None:
        return None
    x, y = strokes["x"], strokes["y"]
    windows = {
        "x": [0, x[3] + 0.5, size[0], caption["bbox"][1]],
        "y": [
            0,
            max(0, y[1] - AXIS_MARGIN),
            y[0] - 0.5,
            min(size[1], x[3] + AXIS_MARGIN),
        ],
    }
    return (
        windows
        if (
            all(inside_box(box, [0, 0, *size]) for box in windows.values())
            and 0 < windows["x"][3] - windows["x"][1] <= 128
            and 0 < windows["y"][2] - windows["y"][0] <= 360
        )
        else None
    )
