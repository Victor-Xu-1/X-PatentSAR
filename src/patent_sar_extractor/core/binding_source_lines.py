"""Lossless original line views; legacy vertical tuples are locator projections."""

import math
from collections.abc import Mapping

from .source_geometry import _box


def source_line(item):
    if isinstance(item, Mapping):
        if "y0" not in item or "text" not in item:
            raise ValueError("Original binding line lacks text or coordinate")
        line = dict(item)
    elif isinstance(item, (tuple, list)) and len(item) == 2:
        line = {"y0": item[0], "text": item[1]}
    else:
        raise TypeError("Malformed original binding line")
    y, text = line["y0"], line["text"]
    if type(y) not in {int, float} or not math.isfinite(y) or not 0 <= y <= 1_000_000:
        raise ValueError("Invalid original binding line coordinate")
    if not isinstance(text, str) or len(text) > 100000:
        raise ValueError("Invalid bounded original binding line text")
    if "bbox" in line:
        rectangle = _box(line["bbox"])
        if (
            min(rectangle) < 0
            or max(rectangle) > 1_000_000
            or abs(rectangle.y0 - y) > 0.02
            or line.get("source") not in {"native", "page_ocr"}
            or line.get("geometry_space") != "rendered"
        ):
            raise ValueError("Unproved original binding line frame")
    return line


def source_line_map(raw):
    if not isinstance(raw, Mapping) or len(raw) > 20000:
        raise ValueError("Original binding line map exceeds its page bound")
    result = {}
    for key, rows in raw.items():
        if isinstance(key, bool) or not str(key).isdigit() or not 0 <= int(key) < 20000:
            raise ValueError("Invalid original binding line page")
        if not isinstance(rows, (list, tuple)) or len(rows) > 50000:
            raise ValueError("Original binding lines exceed their page bound")
        if int(key) in result:
            raise ValueError("Duplicate original binding line page")
        lines = [source_line(row) for row in rows]
        result[int(key)] = sorted(
            (line for line in lines if line["text"].strip()),
            key=lambda line: (line["y0"], line.get("bbox", [0])[0]),
        )
    return result


def line_locators(lines):
    """A view only: no fabricated boxes or replacement of raw observations."""
    return [(float(line["y0"]), line["text"]) for line in lines]


def merged_source_lines(profile, cache):
    """A verified original cache owns its rich observations; profile hints remain."""
    observed, hints = source_line_map(cache), source_line_map(profile)
    for page, lines in hints.items():
        existing = {(line["y0"], line["text"]) for line in observed.get(page, [])}
        observed.setdefault(page, []).extend(
            {"y0": line["y0"], "text": line["text"]}
            for line in lines
            if (line["y0"], line["text"]) not in existing
        )
        observed[page].sort(key=lambda line: (line["y0"], line.get("bbox", [0])[0]))
    return observed
