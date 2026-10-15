"""Bounded whole-line pixels when a detector omits terminal caption ink."""

import math

import cv2
import numpy as np


def complete_line_bounds(image, boxes, border, dpi):
    """Return an observed ink rectangle, never a number-dependent expansion.

    Only a short physical text line inside the same original cell is eligible.
    Other rows, tall diagram envelopes and already covered pixels do not request
    a second read. The returned coordinates use the unchanged OCR-image frame.
    """
    if (
        image.ndim != 3
        or image.shape[2] != 3
        or image.dtype != np.uint8
        or image.shape[0] * image.shape[1] > 8_000_000
        or type(dpi) is not int
        or dpi not in {400, 600}
        or type(border) is not int
        or not 0 < border <= 32
    ):
        raise ValueError("Invalid bounded caption line image")
    if not boxes:
        return _undetected_line_bounds(image, dpi)
    if any(not all(math.isfinite(v) for v in box) for box in boxes):
        raise ValueError("Invalid detected caption line geometry")
    x0, y0 = min(box[0] for box in boxes), min(box[1] for box in boxes)
    x1, y1 = max(box[2] for box in boxes), max(box[3] for box in boxes)
    if not (0 <= x0 < x1 <= image.shape[1] and 0 <= y0 < y1 <= image.shape[0]):
        raise ValueError("Detected caption line leaves its owned cell")
    top, bottom = (
        max(0, math.floor(y0) - border),
        min(image.shape[0], math.ceil(y1) + border),
    )
    ink = cv2.cvtColor(image[top:bottom], cv2.COLOR_RGB2GRAY) < 180
    components, _, _, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    # A terminal character omitted from a caption is disconnected from its word.
    # One solid rule/diagram patch cannot become a new whole-text observation.
    if not 3 <= components <= 513:
        return None
    ink_y, ink_x = np.where(ink)
    if not len(ink_x):
        return None
    left, right = int(ink_x.min()), int(ink_x.max()) + 1
    first, last = int(ink_y.min()) + top, int(ink_y.max()) + top + 1
    if last - first > 12 * dpi / 72:
        return None
    if left >= x0 - 2 and right <= x1 + 2:
        return None
    return left, first, right, last


def _undetected_line_bounds(image, dpi):
    """Positive original ink only; an empty detector response is not a blank cell."""
    ink = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) < 180
    occupied = np.flatnonzero(ink.any(axis=1))
    if not len(occupied):
        return None
    gap = max(1, math.ceil(dpi / 72 * 0.7))
    if np.any(np.diff(occupied) > gap):
        return None  # Distinct physical rows never become a single recognition input.
    first, last = int(occupied[0]), int(occupied[-1]) + 1
    components, _, _, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    if last - first > 12 * dpi / 72 or not 3 <= components <= 513:
        return None
    horizontal = np.flatnonzero(ink[first:last].any(axis=0))
    return int(horizontal[0]), first, int(horizontal[-1]) + 1, last
