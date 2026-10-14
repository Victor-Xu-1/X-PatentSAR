"""Original pixel-row ownership for bounded multiline header observations."""

import hashlib
import math

import cv2
import numpy as np

from .cell_ocr_scores import confidence_score


def header_line_frame(image, border, dpi):
    """Read complete physical rows without endpoint dictionaries or text repair.

    Small gaps within glyphs/subscripts stay in one row. Every dark pixel must
    belong to the retained row inventory. Touching/tall/over-bound input cannot
    fall back to apparently qualified detector text. One-line cells retain the
    existing direct reader. All returned coordinates use its ink-crop frame.
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
        raise ValueError("Invalid original header line frame")
    ink = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) < 180
    occupied = np.flatnonzero(ink.any(axis=1))
    if not len(occupied):
        return None
    groups = np.split(
        occupied,
        np.flatnonzero(np.diff(occupied) > max(1, math.ceil(dpi / 72 * 0.7))) + 1,
    )
    if len(groups) == 1 and (groups[0][-1] - groups[0][0] + 1) * 72 / dpi <= 12:
        return None
    packet = {
        "version": 1,
        "status": "unresolved",
        "image_shape": list(image.shape),
        "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "row_bounds": [],
        "ink_pixels": int(ink.sum()),
    }
    if not 2 <= len(groups) <= 8:
        return packet
    for rows in groups:
        y0, y1 = int(rows[0]), int(rows[-1]) + 1
        x = np.flatnonzero(ink[y0:y1].any(axis=0))
        x0, x1 = int(x[0]), int(x[-1]) + 1
        packet["row_bounds"].append([x0, y0, x1, y1])
        if y1 - y0 > 12 * dpi / 72:
            packet["row_bounds"] = []
            return packet
    return packet


def observe_header_lines(image, engine, border, dpi, *, frame):
    """Recognize every inventoried row with the same engine, no text repair."""
    packet = frame
    parts = []
    for x0, y0, x1, y1 in packet["row_bounds"]:
        clip = cv2.copyMakeBorder(
            image[y0:y1, x0:x1],
            border,
            border,
            border,
            border,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255),
        )
        result, _ = engine(clip, use_det=False, use_cls=False)
        if (
            len(result or []) != 1
            or len(result[0]) != 2
            or not isinstance(result[0][0], str)
        ):
            return parts, packet
        parts.append(
            {
                "text": result[0][0],
                "confidence": confidence_score(result[0][1]),
                "bbox": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                "coordinate_space": "cell_ink_crop_pixels",
                "method": "physical_header_line",
            }
        )
    packet["status"] = (
        "observed"
        if parts and all(p["text"].strip() and p["confidence"] >= 0.85 for p in parts)
        else "unresolved"
    )
    return parts, packet
