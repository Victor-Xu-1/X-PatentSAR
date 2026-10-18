"""Bounded original-ink word frames and deterministic recognition views.

This module assigns no text, molecule, identifier or scientific role. A view is
derived from every retained original ink pixel, never a corrected string.
"""

import math

import cv2
import numpy as np

MAX_WORD_PIXELS = 8_000_000
MAX_WORDS = 32


def _mask(mask, dpi):
    if (
        not isinstance(mask, np.ndarray)
        or mask.ndim != 2
        or not all(mask.shape)
        or mask.size > MAX_WORD_PIXELS
        or mask.dtype not in (np.dtype("bool"), np.dtype("uint8"))
        or np.any(mask > 1)
        or type(dpi) is not int
        or dpi not in (400, 600)
    ):
        raise ValueError("Invalid bounded original-word pixel frame")


def _word_angles(mask, words):
    angles = []
    for left, top, right, bottom in words:
        points = np.column_stack(np.nonzero(mask[top:bottom, left:right])[::-1]).astype(
            np.float32
        )
        corners = cv2.boxPoints(cv2.minAreaRect(points))
        edges = [corners[(i + 1) % 4] - corners[i] for i in range(4)]
        lengths = [float(np.linalg.norm(edge)) for edge in edges]
        if min(lengths) < 1 or max(lengths) / min(lengths) < 1.4:
            continue
        edge = edges[int(np.argmax(lengths))]
        angle = math.degrees(math.atan2(float(edge[1]), float(edge[0])))
        angles.append((angle + 90) % 180 - 90)
    return angles


def _orientation(angles, words, dpi):
    candidates = {}
    for anchor in angles:
        offsets = [((value - anchor + 90) % 180) - 90 for value in angles]
        members = tuple(i for i, offset in enumerate(offsets) if abs(offset) <= 8)
        if len(members) >= 2 and len(members) > len(angles) / 2:
            value = anchor + float(np.median([offsets[i] for i in members]))
            candidates[members] = (value + 90) % 180 - 90
    if not candidates:
        return None
    longest = max(map(len, candidates))
    choices = [value for key, value in candidates.items() if len(key) == longest]
    if len(choices) != 1:
        return None
    angle = choices[0]
    if abs(angle) > 80:
        top = max(b[1] for b in words) - min(b[1] for b in words)
        bottom = max(b[3] for b in words) - min(b[3] for b in words)
        tolerance = 3 * dpi / 72
        if bottom < top and bottom <= tolerance:
            return -90.0
        if top < bottom and top <= tolerance:
            return 90.0
        return None  # Ink alone does not prove which vertical direction is upright.
    return angle


def word_frame(mask, dpi):
    """Retain all column-separated words before selecting a reading direction."""
    _mask(mask, dpi)
    columns = np.flatnonzero(mask.any(axis=0))
    if not len(columns):
        return None
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    if not 2 <= count <= 2049:
        return None
    # Decimal dots and narrow glyphs must stay in their physical word even at a
    # different font scale. This groups pixels only; OCR still reads each whole
    # frame, and no character strings are concatenated into a number.
    glyph_extent = float(np.median(np.max(stats[1:, 2:4], axis=1)))
    gap = math.ceil(max(2 * dpi / 72, min(12 * dpi / 72, glyph_extent * 0.5)))
    groups = np.split(
        columns,
        np.flatnonzero(np.diff(columns) > gap) + 1,
    )
    if not 3 <= len(groups) <= MAX_WORDS:
        return None
    words = []
    for group in groups:
        left, right = int(group[0]), int(group[-1]) + 1
        rows = np.flatnonzero(mask[:, left:right].any(axis=1))
        words.append([left, int(rows[0]), right, int(rows[-1]) + 1])
    angle = _orientation(_word_angles(mask, words), words, dpi)
    if angle is None:
        return None
    return {"version": 1, "word_bounds": words, "angle": angle}


def valid_word_frame(frame, mask, dpi):
    if (
        not isinstance(frame, dict)
        or set(frame) != {"version", "word_bounds", "angle"}
        or type(frame["version"]) is not int
        or frame["version"] != 1
        or type(frame["angle"]) not in (int, float)
        or not math.isfinite(frame["angle"])
        or not isinstance(frame["word_bounds"], list)
        or not 3 <= len(frame["word_bounds"]) <= MAX_WORDS
        or any(
            not isinstance(box, list)
            or len(box) != 4
            or any(type(value) is not int for value in box)
            for box in frame["word_bounds"]
        )
    ):
        return False
    try:
        return frame == word_frame(mask, dpi)
    except (ValueError, TypeError, OverflowError):
        return False


def rectified_word(mask, box, angle, dpi):
    """A reproducible mask-derived view; original PDF coordinates stay separate."""
    _mask(mask, dpi)
    if (
        not isinstance(box, list)
        or len(box) != 4
        or any(type(value) is not int for value in box)
        or not 0 <= box[0] < box[2] <= mask.shape[1]
        or not 0 <= box[1] < box[3] <= mask.shape[0]
        or type(angle) not in (int, float)
        or not math.isfinite(angle)
        or not -90 <= angle <= 90
    ):
        raise ValueError("Invalid original-word rectification geometry")
    word = np.repeat(
        np.where(mask[box[1] : box[3], box[0] : box[2], None], 0, 255).astype(np.uint8),
        3,
        axis=2,
    )
    height, width = word.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
    out_width = math.ceil(abs(matrix[0, 0]) * width + abs(matrix[0, 1]) * height) + 2
    out_height = math.ceil(abs(matrix[0, 0]) * height + abs(matrix[0, 1]) * width) + 2
    border = max(3, round(dpi / 72 * 1.5))
    if (out_width + border * 2) * (out_height + border * 2) > MAX_WORD_PIXELS:
        raise ValueError("Rectified original word exceeds its pixel bound")
    matrix[0, 2] += out_width / 2 - width / 2
    matrix[1, 2] += out_height / 2 - height / 2
    view = cv2.warpAffine(
        word, matrix, (out_width, out_height), borderValue=(255, 255, 255)
    )
    return cv2.copyMakeBorder(
        view, border, border, border, border, cv2.BORDER_CONSTANT, value=(255, 255, 255)
    )
