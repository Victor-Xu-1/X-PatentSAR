"""Call-local paired source for a title and its independently closed rulings."""

import re

from .cell_raster import cell_pixel_rect, render_cell_raster
from .plot_reference_pixels import pixel_reading
from .shared_cell_raster import shared_cell_view
from .source_cell_pixels import MAX_CELL_PIXELS, source_window


def shared_title_bounds(bounds, size, cells):
    """Only a complete, bounded first-row owner; never expand a source budget."""
    if not cells or any(cell[3] <= bounds[1] for cell in cells):
        return None  # Historical outside-edge witnesses retain their own recipe.
    windows = [
        source_window(bounds, size),
        *[source_window(cell, size) for cell in cells],
    ]
    owner = [
        min(window[0] for window in windows),
        min(window[1] for window in windows),
        max(window[2] for window in windows),
        max(window[3] for window in windows),
    ]
    if any(
        extent.width * extent.height > MAX_CELL_PIXELS
        for dpi in (400, 600)
        for extent in (cell_pixel_rect(owner, dpi),)
    ):
        return None
    return owner


def observe_shared_title(page, bounds, size, cells):
    """Two existing renders per call, not an additional recognizer or cache."""
    owner = shared_title_bounds(bounds, size, cells)
    return (
        None
        if owner is None
        else (owner, {dpi: render_cell_raster(page, owner, dpi) for dpi in (400, 600)})
    )


def shared_title_pixels(shared, bounds, *, resolutions=(400, 600)):
    owner, sources = shared
    return {
        "bbox": list(bounds),
        "readings": [
            pixel_reading(view.image, dpi, source_window=view.source_window)
            for dpi in resolutions
            for view in (shared_cell_view(sources[dpi], owner, bounds, dpi),)
        ],
    }


def valid_shared_title_sources(bounds, size, cells, raster, rulings, *, active):
    """Every retained subview must name the same geometry/digest at each dpi."""
    if raster is not None and not isinstance(raster, dict):
        return False
    owner = shared_title_bounds(bounds, size, cells) if active else None
    packets = [
        (raster or {}).get("pixels"),
        *[ruling["pixels"] for ruling in rulings],
    ]
    digests = {}
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        readings = packet.get("readings", [])
        if not isinstance(readings, list):
            return False
        for reading in readings:
            if not isinstance(reading, dict):
                return False
            dpi = reading.get("dpi")
            if type(dpi) is not int or dpi not in {400, 600}:
                return False
            window = reading.get("source_window") or {}
            if not isinstance(window, dict):
                return False
            if owner is None:
                if window.get("version") == 3:
                    return False
            else:
                if window.get("version") != 3 or window.get("source_bbox") != owner:
                    return False
                digest = window.get("source_pixel_sha256")
                if (
                    not isinstance(digest, str)
                    or re.fullmatch(r"[a-f0-9]{64}", digest) is None
                ):
                    return False
                if dpi in digests and digests[dpi] != digest:
                    return False
                digests[dpi] = digest
    return True
