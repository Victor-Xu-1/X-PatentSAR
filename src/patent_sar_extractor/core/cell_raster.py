"""Complete original cell raster with explicit, replayable reading coordinates."""

import hashlib
import json
import math
import re
from dataclasses import dataclass

import fitz
import numpy as np

from .cell_rendering import CellRenderLimit, historical_cell_image, original_cell_pixmap
from .cell_rule_pixels import MAX_RULE_THICKNESS_PT
from .cell_window import observe_cell_windows


@dataclass(frozen=True)
class CellRaster:
    image: np.ndarray
    frame: dict
    source_window: dict


def _pixel_digest(image):
    data = memoryview(image) if image.flags.c_contiguous else image.tobytes()
    return hashlib.sha256(data).hexdigest()


def _bounds(bounds):
    return (
        isinstance(bounds, (list, tuple, fitz.Rect))
        and len(bounds) == 4
        and all(type(v) in {int, float} and math.isfinite(v) for v in bounds)
        and 0 <= bounds[0] < bounds[2] <= 1_000_000
        and 0 <= bounds[1] < bounds[3] <= 1_000_000
    )


def cell_pixel_rect(bounds, dpi):
    """The actual MuPDF device frame, shared by capture and point projection."""
    if not _bounds(bounds) or type(dpi) is not int or not 1 <= dpi <= 1200:
        raise ValueError("Invalid original cell device geometry")
    return (fitz.Rect(bounds) * fitz.Matrix(dpi / 72, dpi / 72)).irect


def render_cell_raster(
    page, bounds, dpi, *, maximum_pixels=8_000_000, purpose="pixels"
):
    """Render the full caller-owned cell once, without fixed inward cropping.

    Original-source pixels and the selected reading view have separate hashes.
    All OCR/role/value acceptance and independent source replay remain outside
    this geometry adapter. It never starts OCR, a provider, or a second reader.
    """
    if type(maximum_pixels) is not int or not 0 < maximum_pixels <= 8_000_000:
        raise ValueError("Invalid original-cell pixel budget")
    if type(purpose) is not str or purpose not in {"pixels", "text"}:
        raise ValueError("Unknown original cell reading purpose")
    extent = cell_pixel_rect(bounds, dpi)
    if extent.is_empty or not page.rect.contains(fitz.Rect(bounds)):
        raise ValueError("Original cell leaves its source page")
    if extent.width * extent.height > maximum_pixels:
        raise CellRenderLimit("Original cell exceeds its rendered pixel budget")
    pixmap = original_cell_pixmap(
        page, matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=fitz.Rect(bounds)
    )
    source = np.frombuffer(pixmap.samples, np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )[:, :, :3]
    if list(source.shape) != [extent.height, extent.width, 3]:
        raise ValueError("Original cell device frame differs from its source")
    window, proposed = observe_cell_windows(
        source, dpi, allow_text_frame=purpose == "text"
    )
    support_packet = None
    support_limit = None
    if (
        purpose == "text"
        and dpi == 400
        and window.frame_strips is None
        and proposed.frame_strips is not None
    ):
        high_extent = cell_pixel_rect(bounds, 600)
        if high_extent.width * high_extent.height <= maximum_pixels:
            from .cell_frame_support import supported_cell_window

            support = render_cell_raster(
                page, bounds, 600, maximum_pixels=maximum_pixels, purpose="text"
            )
            supported = supported_cell_window(proposed, bounds, support)
            if supported is not None:
                window = supported
                support_packet = {
                    "frame": support.frame,
                    "window": support.source_window,
                }
        else:
            support_limit = maximum_pixels
    image = window.view(source)
    source_digest = _pixel_digest(source)
    reading_digest = (
        source_digest
        if window.bounds == (0, 0, source.shape[1], source.shape[0])
        else _pixel_digest(image)
    )
    return CellRaster(
        image,
        {
            "dpi": dpi,
            "shape": list(image.shape),
            "pixel_sha256": reading_digest,
        },
        {
            "version": 1,
            "purpose": purpose,
            "source_shape": list(source.shape),
            "source_pixel_sha256": source_digest,
            "read_bounds": list(window.bounds),
            "frame_strips": list(window.frame_strips) if window.frame_strips else None,
            **({"support": support_packet} if support_packet is not None else {}),
            **({"support_limit": support_limit} if support_limit is not None else {}),
        },
    )


def valid_source_window(window, bounds, dpi, reading_shape):
    """Validate geometry only; a saved digest cannot establish original truth."""
    if isinstance(window, dict) and window.get("version") == 3:
        from .shared_cell_raster import valid_shared_source_window

        return valid_shared_source_window(window, bounds, dpi, reading_shape)
    if isinstance(window, dict) and window.get("version") == 2:
        from .open_cell_raster import valid_open_source_window

        return valid_open_source_window(window, bounds, dpi, reading_shape)
    if (
        not isinstance(window, dict)
        or set(window) - {"support", "support_limit"}
        != {
            "version",
            "purpose",
            "source_shape",
            "source_pixel_sha256",
            "read_bounds",
            "frame_strips",
        }
        or type(window.get("version")) is not int
        or window["version"] != 1
        or type(window.get("purpose")) is not str
        or window["purpose"] not in {"pixels", "text"}
        or not isinstance(window.get("source_shape"), list)
        or len(window["source_shape"]) != 3
        or any(type(n) is not int or n <= 0 for n in window["source_shape"])
        or window["source_shape"][2] != 3
        or math.prod(window["source_shape"][:2]) > 8_000_000
        or not isinstance(window.get("source_pixel_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", window["source_pixel_sha256"])
    ):
        return False
    try:
        extent = cell_pixel_rect(bounds, dpi)
    except (TypeError, ValueError, OverflowError):
        return False
    if window["source_shape"] != [extent.height, extent.width, 3]:
        return False
    box = window["read_bounds"]
    height, width = window["source_shape"][:2]
    if (
        not isinstance(box, list)
        or len(box) != 4
        or any(type(n) is not int for n in box)
        or not 0 <= box[0] < box[2] <= width
        or not 0 <= box[1] < box[3] <= height
        or not isinstance(reading_shape, list)
        or any(type(n) is not int for n in reading_shape)
        or reading_shape != [box[3] - box[1], box[2] - box[0], 3]
    ):
        return False
    strips = window["frame_strips"]
    if "support_limit" in window:
        limit = window["support_limit"]
        high_extent = cell_pixel_rect(bounds, 600)
        if (
            type(limit) is not int
            or not 0 < limit <= 8_000_000
            or height * width > limit
            or high_extent.width * high_extent.height <= limit
            or dpi != 400
            or window["purpose"] != "text"
            or strips is not None
            or "support" in window
        ):
            return False
    if "support" in window:
        from .cell_frame_support import valid_support

        if (
            dpi != 400
            or window["purpose"] != "text"
            or strips is None
            or not valid_support(window["support"], bounds)
        ):
            return False
    if strips is None:
        return box == [0, 0, width, height]
    return (
        window["purpose"] == "text"
        and isinstance(strips, list)
        and len(strips) == 4
        and all(
            type(n) is int and 0 < n <= math.ceil(dpi * MAX_RULE_THICKNESS_PT / 72) + 1
            for n in strips
        )
        and box[2] - box[0] >= 3
        and box[3] - box[1] >= 3
        and box[0] >= strips[0]
        and box[1] >= strips[1]
        and box[2] + strips[2] <= width
        and box[3] + strips[3] <= height
    )


def cell_window_origin(window, bounds, dpi, reading_shape):
    """Project reading pixels using their proved source window, never an inset."""
    if not valid_source_window(window, bounds, dpi, reading_shape):
        raise ValueError("Invalid original cell reading window")
    extent = cell_pixel_rect(
        window["source_bbox"] if window["version"] == 3 else bounds, dpi
    )
    return [
        (extent.x0 + window["read_bounds"][0]) * 72 / dpi,
        (extent.y0 + window["read_bounds"][1]) * 72 / dpi,
    ]


def cell_window_identity(window):
    """Full validated geometry identity, including any original support frame."""
    return json.dumps(window, sort_keys=True, separators=(",", ":"), allow_nan=False)


def original_reading_image(page, bounds, dpi, reading):
    """Reopen a retained reading's exact window; absent v1 windows stay history.

    Malformed/new packets cannot fall back to a historical crop. No OCR or
    scientific text qualification occurs during this original-pixel readback.
    """
    if not isinstance(reading, dict):
        raise TypeError("Invalid retained original cell reading")
    if "source_window" not in reading:
        return historical_cell_image(page, bounds, dpi)
    window = reading["source_window"]
    frame = reading.get("source_frame")
    shape = frame.get("shape") if isinstance(frame, dict) else None
    if not valid_source_window(window, bounds, dpi, shape):
        raise ValueError("Invalid retained original cell window")
    if window["version"] == 3:
        from .shared_cell_raster import render_shared_cell_raster

        observed = render_shared_cell_raster(page, window["source_bbox"], bounds, dpi)
    elif window["version"] == 2:
        from .open_cell_raster import render_open_cell_raster

        owner = window["open_grid"]
        observed = render_open_cell_raster(
            page, bounds, dpi, owner["grid_edges"], owner["fragment"], owner["column"]
        )
    else:
        observed = render_cell_raster(
            page,
            bounds,
            dpi,
            purpose=window["purpose"],
            maximum_pixels=window.get("support_limit", 8_000_000),
        )
    if observed is None or observed.source_window != window:
        raise ValueError("Original full source differs from its retained cell window")
    return observed.image


def retained_pixel_origin(reading, bounds, dpi):
    """One actual/new or explicitly historical point origin for pixel readers."""
    if "source_window" in reading:
        return cell_window_origin(
            reading["source_window"], bounds, dpi, reading.get("shape")
        )
    return [
        math.floor((bounds[0] + 1.5) * dpi / 72) * 72 / dpi,
        math.floor((bounds[1] + 1.2) * dpi / 72) * 72 / dpi,
    ]
