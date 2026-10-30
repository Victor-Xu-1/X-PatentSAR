"""A touched horizontal rule stays in the literal text view, never painted out."""

import math

import cv2
import numpy as np

from .cell_rule_pixels import MAX_RULE_THICKNESS_PT
from .cell_window import CellWindow


def preserved_cell_window(image, dpi, proposed):
    """Exclude three proved rule strips only if their non-rule contacts are absent.

    The ordinary selector has already inventoried all four complete rule bands
    and conserved every excluded non-rule pixel. Its full crop was rejected for
    contact. Here exactly one horizontal edge, including ALL its attached ink,
    remains in the byte-identical source view. Only the retained rule band is
    omitted from a temporary connectivity analysis, never from model input.
    Side contact, two touched horizontal edges and ambiguous choices refuse.
    This geometry does not qualify text, a role, an identifier or a measurement.
    """
    if proposed.frame_strips is None or dpi not in {400, 600}:
        return None
    x0, y0, x1, y1 = proposed.bounds
    left, top, right, bottom = proposed.frame_strips
    ink = np.any(image != 255, axis=2)
    candidates = []
    for edge in ("top", "bottom"):
        analysis = ink.copy()
        if edge == "top":
            analysis[:y0] = False
            bounds, strips = (x0, 0, x1, y1), (left, 0, right, bottom)
        else:
            analysis[y1:] = False
            bounds, strips = (x0, y0, x1, image.shape[0]), (left, top, right, 0)
        a, b, c, d = bounds
        excluded = analysis.copy()
        excluded[b:d, a:c] = False
        _, labels = cv2.connectedComponents(analysis.astype(np.uint8), connectivity=8)
        components = np.unique(labels[excluded])
        if (
            not len(components)
            or np.any(components == 0)
            or np.any(np.isin(labels[b:d, a:c], components))
        ):
            continue
        candidates.append((CellWindow(bounds, strips), edge))
    return candidates[0] if len(candidates) == 1 else None


def valid_preserved_source_window(window, bounds, dpi, reading_shape):
    """Bounded geometry only; replay must recompute the original cut and hashes."""
    from .cell_raster import valid_source_window

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
            "preserved_edge",
            "role_text_height",
            "maximum_pixels",
        }
        or type(window["version"]) is not int
        or window["version"] != 4
        or window["purpose"] != "text"
        or type(window["role_text_height"]) is not int
        or not 0 < window["role_text_height"] <= 128
        or type(window["maximum_pixels"]) is not int
        or not 0 < window["maximum_pixels"] <= 8_000_000
        or type(dpi) is not int
        or dpi not in {400, 600}
        or type(window["preserved_edge"]) is not str
        or window["preserved_edge"] not in {"top", "bottom"}
        or not isinstance(window["source_shape"], list)
        or len(window["source_shape"]) != 3
    ):
        return False
    height, width, _channels = window["source_shape"]
    complete = {
        key: value
        for key, value in window.items()
        if key not in {"preserved_edge", "role_text_height", "maximum_pixels"}
    }
    complete.update(version=1, read_bounds=[0, 0, width, height], frame_strips=None)
    if not valid_source_window(complete, bounds, dpi, window["source_shape"]):
        return False
    if height * width > window["maximum_pixels"]:
        return False
    box, strips = window["read_bounds"], window["frame_strips"]
    zero = 1 if window["preserved_edge"] == "top" else 3
    maximum = math.ceil(dpi * MAX_RULE_THICKNESS_PT / 72) + 1
    if (
        not isinstance(strips, list)
        or len(strips) != 4
        or any(
            type(value) is not int
            or not (value == 0 if index == zero else 0 < value <= maximum)
            for index, value in enumerate(strips)
        )
        or not isinstance(box, list)
        or len(box) != 4
        or any(type(value) is not int for value in box)
        or not 0 <= box[0] < box[2] <= width
        or not 0 <= box[1] < box[3] <= height
        or box[2] - box[0] < 3
        or box[3] - box[1] < 3
        or not isinstance(reading_shape, list)
        or any(type(value) is not int for value in reading_shape)
        or reading_shape != [box[3] - box[1], box[2] - box[0], 3]
    ):
        return False
    left, top, right, bottom = strips
    return (
        box[0] >= left
        and box[2] + right <= width
        and (box[1] == 0 if zero == 1 else box[1] >= top)
        and (box[3] == height if zero == 3 else box[3] + bottom <= height)
    )
