"""Exact subviews of one bounded original render, without pixel resampling."""

import re

import fitz

from .cell_raster import CellRaster, _pixel_digest, cell_pixel_rect, render_cell_raster


def valid_shared_source_window(window, bounds, dpi, reading_shape):
    """Geometry is necessary, not sufficient: replay owns the original digest."""
    if (
        not isinstance(window, dict)
        or set(window)
        != {
            "version",
            "purpose",
            "source_bbox",
            "source_shape",
            "source_pixel_sha256",
            "read_bounds",
            "frame_strips",
        }
        or type(window["version"]) is not int
        or window["version"] != 3
        or window["purpose"] != "pixels"
        or window["frame_strips"] is not None
        or type(dpi) is not int
        or dpi not in {400, 600}
        or not isinstance(window["source_bbox"], list)
        or not isinstance(window["source_pixel_sha256"], str)
        or re.fullmatch(r"[a-f0-9]{64}", window["source_pixel_sha256"]) is None
    ):
        return False
    try:
        owner = cell_pixel_rect(window["source_bbox"], dpi)
        target = cell_pixel_rect(bounds, dpi)
        contains = fitz.Rect(window["source_bbox"]).contains(fitz.Rect(bounds))
    except (ValueError, TypeError, OverflowError):
        return False
    shape, view = window["source_shape"], window["read_bounds"]
    return (
        contains
        and 0 < owner.width * owner.height <= 8_000_000
        and isinstance(shape, list)
        and all(type(value) is int for value in shape)
        and shape == [owner.height, owner.width, 3]
        and isinstance(view, list)
        and all(type(value) is int for value in view)
        and view
        == [
            target.x0 - owner.x0,
            target.y0 - owner.y0,
            target.x1 - owner.x0,
            target.y1 - owner.y0,
        ]
        and isinstance(reading_shape, list)
        and all(type(value) is int for value in reading_shape)
        and reading_shape == [target.height, target.width, 3]
    )


def shared_cell_view(source, source_bounds, bounds, dpi):
    """Select original bytes only; no inset, resize, threshold or erasure."""
    owner = cell_pixel_rect(source_bounds, dpi)
    target = cell_pixel_rect(bounds, dpi)
    if (
        not isinstance(source, CellRaster)
        or source.source_window.get("version") != 1
        or source.source_window.get("purpose") != "pixels"
        or source.source_window.get("frame_strips") is not None
        or source.source_window.get("read_bounds") != [0, 0, owner.width, owner.height]
        or source.source_window.get("source_pixel_sha256")
        != source.frame.get("pixel_sha256")
        or source.frame.get("dpi") != dpi
        or list(source.image.shape) != [owner.height, owner.width, 3]
        or not fitz.Rect(source_bounds).contains(fitz.Rect(bounds))
    ):
        raise ValueError("Invalid shared original render owner")
    view = [
        target.x0 - owner.x0,
        target.y0 - owner.y0,
        target.x1 - owner.x0,
        target.y1 - owner.y0,
    ]
    image = source.image[view[1] : view[3], view[0] : view[2]]
    window = {
        "version": 3,
        "purpose": "pixels",
        "source_bbox": list(source_bounds),
        "source_shape": list(source.image.shape),
        "source_pixel_sha256": source.frame["pixel_sha256"],
        "read_bounds": view,
        "frame_strips": None,
    }
    if not valid_shared_source_window(window, bounds, dpi, list(image.shape)):
        raise ValueError("Shared original reading leaves its bounded owner")
    return CellRaster(
        image,
        {"dpi": dpi, "shape": list(image.shape), "pixel_sha256": _pixel_digest(image)},
        window,
    )


def render_shared_cell_raster(page, source_bounds, bounds, dpi):
    """Replay through the SAME original renderer and retained parent geometry."""
    source = render_cell_raster(page, source_bounds, dpi)
    return shared_cell_view(source, source_bounds, bounds, dpi)
