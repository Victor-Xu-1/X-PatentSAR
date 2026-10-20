"""Bounded paired-resolution original geometry, without text or model voting."""

import fitz
import numpy as np


def supported_cell_window(proposed, bounds, support):
    """All high-resolution content must fit the proposed lower reading window.

    The lower proposal already conserves every excluded non-rule pixel. The
    SAME original PDF's existing600dpi view must independently separate all
    non-white content from all four rules. A caller flag or two OCR strings
    cannot provide this evidence. Original readback repeats both renderings.
    """
    if proposed.frame_strips is None or support.source_window["frame_strips"] is None:
        return None
    yy, xx = np.where(np.any(support.image != 255, axis=2))
    if not len(xx):
        return None
    high = (fitz.Rect(bounds) * fitz.Matrix(600 / 72, 600 / 72)).irect
    low = (fitz.Rect(bounds) * fitz.Matrix(400 / 72, 400 / 72)).irect
    read = support.source_window["read_bounds"]
    content = [
        (high.x0 + read[0] + int(xx.min())) * 72 / 600,
        (high.y0 + read[1] + int(yy.min())) * 72 / 600,
        (high.x0 + read[0] + int(xx.max()) + 1) * 72 / 600,
        (high.y0 + read[1] + int(yy.max()) + 1) * 72 / 600,
    ]
    x0, y0, x1, y1 = proposed.bounds
    target = [
        (low.x0 + x0) * 72 / 400,
        (low.y0 + y0) * 72 / 400,
        (low.x0 + x1) * 72 / 400,
        (low.y0 + y1) * 72 / 400,
    ]
    return proposed if fitz.Rect(target).contains(fitz.Rect(content)) else None


def valid_support(support, bounds):
    from .cell_raster import valid_source_window

    if not isinstance(support, dict) or set(support) != {"frame", "window"}:
        return False
    frame, window = support["frame"], support["window"]
    if (
        not isinstance(frame, dict)
        or set(frame) != {"dpi", "shape", "pixel_sha256"}
        or type(frame.get("dpi")) is not int
        or frame["dpi"] != 600
        or not isinstance(window, dict)
        or "support" in window
        or window.get("purpose") != "text"
        or window.get("frame_strips") is None
    ):
        return False
    import re

    return (
        isinstance(frame.get("pixel_sha256"), str)
        and re.fullmatch(r"[a-f0-9]{64}", frame["pixel_sha256"]) is not None
        and valid_source_window(window, bounds, 600, frame.get("shape"))
    )
