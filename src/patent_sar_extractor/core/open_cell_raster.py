"""Conservative original open-grid text views; every excluded pixel is a rule."""

import math
import re

import cv2
import fitz
import numpy as np

from .cell_rendering import CellRenderLimit, original_cell_pixmap
from .cell_rule_pixels import (
    MAX_RULE_THICKNESS_PT,
    include_original_rule_joints,
    original_rule_band,
)
from .source_grid_edges import edge_intervals


def valid_open_owner(edges, fragment, column, bounds):
    try:
        xs = edges["xs"]
        return (
            type(column) is int
            and 0 <= column < len(xs) - 1
            and isinstance(fragment, dict)
            and set(fragment) == {"edge", "bbox", "status"}
            and fragment in edge_intervals(edges)
            and fragment["status"] == "observed_columns"
            and edges["rule_frame"] is not None
            and bounds
            == [xs[column], fragment["bbox"][1], xs[column + 1], fragment["bbox"][3]]
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def open_rule_window(image, dpi, edge):
    """Return only a disconnected three-edge view; never erase attached ink."""
    if (
        not isinstance(image, np.ndarray)
        or image.ndim != 3
        or image.shape[2] != 3
        or image.dtype != np.uint8
        or image.shape[0] <= 0
        or image.shape[1] <= 0
        or image.shape[0] * image.shape[1] > 8_000_000
        or type(dpi) is not int
        or dpi not in {400, 600}
        or type(edge) is not str
        or edge not in {"top", "bottom"}
    ):
        raise ValueError("Invalid bounded original open-grid pixels")
    height, width = image.shape[:2]
    full = np.any(image != 255, axis=2)
    horizontal = original_rule_band(
        full, 0, 0 if edge == "bottom" else height - 1, 0, width, dpi
    )
    left = original_rule_band(full, 1, 0, 0, height, dpi)
    right = original_rule_band(full, 1, width - 1, 0, height, dpi)
    if horizontal is None or left is None or right is None:
        return None
    x0, x1 = max(left) + 1, min(right)
    y0, y1 = (max(horizontal) + 1, height) if edge == "bottom" else (0, min(horizontal))
    strips = [x0, y0, width - x1, height - y1]
    maximum = math.ceil(dpi * MAX_RULE_THICKNESS_PT / 72) + 1
    open_index = 3 if edge == "bottom" else 1
    if (
        x1 - x0 < 3
        or y1 - y0 < 3
        or any(
            type(value) is not int
            or not (value == 0 if index == open_index else 0 < value <= maximum)
            for index, value in enumerate(strips)
        )
    ):
        return None
    excluded = full.copy()
    excluded[y0:y1, x0:x1] = False
    allowed = np.zeros_like(full)
    allowed[horizontal, :] = True
    allowed[:, left] = True
    allowed[:, right] = True
    include_original_rule_joints(full, allowed, [horizontal, horizontal, left, right])
    if np.any(excluded & ~allowed):
        return None
    _, labels = cv2.connectedComponents(full.astype(np.uint8), connectivity=8)
    components = np.unique(labels[excluded])
    if not len(components) or np.any(components == 0):
        return None
    if np.any(np.isin(labels[y0:y1, x0:x1], components)):
        return None
    return [x0, y0, x1, y1], strips


def render_open_cell_raster(page, bounds, dpi, edges, fragment, column):
    """Select a view only when the actual page proves its complete grid owner."""
    from .cell_raster import CellRaster, _pixel_digest, cell_pixel_rect
    from .source_fragment_native import original_open_grid_matches

    if not valid_open_owner(edges, fragment, column, bounds):
        raise ValueError("Invalid original open-grid cell owner")
    if not original_open_grid_matches(page, edges):
        raise ValueError("Original open-grid frame differs from its source")
    extent = cell_pixel_rect(bounds, dpi)
    if extent.is_empty or not page.rect.contains(fitz.Rect(bounds)):
        raise ValueError("Original open-grid cell leaves its source page")
    if extent.width * extent.height > 8_000_000:
        raise CellRenderLimit("Original open-grid cell exceeds its pixel budget")
    pixmap = original_cell_pixmap(
        page, matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=fitz.Rect(bounds)
    )
    source = np.frombuffer(pixmap.samples, np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )[:, :, :3]
    if list(source.shape) != [extent.height, extent.width, 3]:
        raise ValueError("Original open-grid cell differs from its device frame")
    selected = open_rule_window(source, dpi, fragment["edge"])
    if selected is None:
        return None
    view, strips = selected
    x0, y0, x1, y1 = view
    image = source[y0:y1, x0:x1]
    return CellRaster(
        image,
        {"dpi": dpi, "shape": list(image.shape), "pixel_sha256": _pixel_digest(image)},
        {
            "version": 2,
            "purpose": "text",
            "source_shape": list(source.shape),
            "source_pixel_sha256": _pixel_digest(source),
            "read_bounds": view,
            "frame_strips": strips,
            "open_grid": {"grid_edges": edges, "fragment": fragment, "column": column},
        },
    )


def valid_open_source_window(window, bounds, dpi, reading_shape):
    """Validate bounded ownership/geometry; actual pixels are checked on replay."""
    from .cell_raster import cell_pixel_rect

    if (
        not isinstance(window, dict)
        or set(window)
        != {
            "version",
            "purpose",
            "source_shape",
            "source_pixel_sha256",
            "read_bounds",
            "frame_strips",
            "open_grid",
        }
        or type(window["version"]) is not int
        or window["version"] != 2
        or window["purpose"] != "text"
        or type(dpi) is not int
        or dpi not in {400, 600}
        or not isinstance(window["source_pixel_sha256"], str)
        or re.fullmatch(r"[a-f0-9]{64}", window["source_pixel_sha256"]) is None
        or not isinstance(window["open_grid"], dict)
        or set(window["open_grid"]) != {"grid_edges", "fragment", "column"}
    ):
        return False
    owner = window["open_grid"]
    if not valid_open_owner(
        owner["grid_edges"], owner["fragment"], owner["column"], bounds
    ):
        return False
    try:
        extent = cell_pixel_rect(bounds, dpi)
    except (TypeError, ValueError, OverflowError):
        return False
    height, width = extent.height, extent.width
    strips = window["frame_strips"]
    maximum = math.ceil(dpi * MAX_RULE_THICKNESS_PT / 72) + 1
    zero = 3 if owner["fragment"]["edge"] == "bottom" else 1
    if (
        width * height > 8_000_000
        or window["source_shape"] != [height, width, 3]
        or not isinstance(strips, list)
        or len(strips) != 4
        or any(
            type(value) is not int
            or not (value == 0 if index == zero else 0 < value <= maximum)
            for index, value in enumerate(strips)
        )
    ):
        return False
    left, top, right, bottom = strips
    return (
        width - left - right >= 3
        and height - top - bottom >= 3
        and window["read_bounds"] == [left, top, width - right, height - bottom]
        and reading_shape == [height - top - bottom, width - left - right, 3]
    )
