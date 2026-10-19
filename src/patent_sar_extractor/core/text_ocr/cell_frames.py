"""Complete original cell/row frames; no word guessing or successful-token crops."""

import hashlib

import cv2
import numpy as np

from patent_sar_extractor.core.cell_header_lines import physical_line_frame
from patent_sar_extractor.core.cell_text_limits import row_pixel_limit

MIN_AUXILIARY_SCORE = 0.99  # A conservative quality filter, NOT calibrated accuracy.


def source_rows(image, dpi):
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
        or image.shape[0] * image.shape[1] > 8_000_000
        or dpi not in (400, 600)
    ):
        raise ValueError("Invalid auxiliary original cell frame")
    occupied_y, occupied_x = np.where(image.min(axis=2) < 180)
    if not len(occupied_x):
        return None
    crop = [
        int(occupied_x.min()),
        int(occupied_y.min()),
        int(occupied_x.max()) + 1,
        int(occupied_y.max()) + 1,
    ]
    border = max(3, round(dpi / 72 * 1.5))
    canvas = cv2.copyMakeBorder(
        image[crop[1] : crop[3], crop[0] : crop[2]],
        border,
        border,
        border,
        border,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    frame = physical_line_frame(canvas, border, dpi, maximum_rows=8)
    if frame is None:
        if crop[3] - crop[1] > row_pixel_limit(dpi):
            return None
        rows = [[border, border, canvas.shape[1] - border, canvas.shape[0] - border]]
    else:
        rows = frame["row_bounds"]
    if not 1 <= len(rows) <= 8:
        return None
    images = []
    for x0, y0, x1, y1 in rows:
        row = cv2.copyMakeBorder(
            canvas[y0:y1, x0:x1],
            border,
            border,
            border,
            border,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255),
        )
        if (
            row.shape[0] > 256
            or row.shape[1] > 4096
            or row.shape[0] * row.shape[1] > 1_000_000
        ):
            return None
        images.append(row)
    return {
        "frame": {
            "dpi": dpi,
            "shape": list(image.shape),
            "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        },
        "crop": crop,
        "border": border,
        "shape": list(canvas.shape),
        "pixel_sha256": hashlib.sha256(canvas.tobytes()).hexdigest(),
        "ink_pixels": int((canvas.min(axis=2) < 180).sum()),
        "row_bounds": rows,
        "images": images,
    }


def literal(text):
    """Whitespace comparison only; preserve all printed character identities."""
    return "".join(text.split())
