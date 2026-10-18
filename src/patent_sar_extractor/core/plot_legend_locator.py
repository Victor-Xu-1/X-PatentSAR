"""Literal graphic-key/heading locators from complete original line pixels.

An OCR prefix nominates observation only. It is never removed from raw data or
used to assert a molecule; text and the complete graphic key need pixel proof.
"""

import math
import re

import numpy as np

from .cell_frame_proof import inside_box
from .plot_reference_geometry import legend_heading, literal_bounds
from .plot_reference_marker import marker_extent
from .plot_reference_pixels import observe_pixels, retained_pixels
from .source_geometry import overlaps
from .source_section_roles import section_heading

MAX_LOCATOR_PIXELS = 250_000
_LABEL = re.compile(
    r"(?<!\w)(?:Compound|Cmpd|Cpd|化合物)(?=\s|[-:.：]|\d)", re.IGNORECASE
)
_LINE_FIELDS = {"text", "bbox", "source", "geometry_space"}


def legend_candidate(text):
    if not isinstance(text, str) or len(text) > 4096:
        return None
    if section_heading(text) is not None and not legend_heading(text):
        return None  # A known preparation/assay role is never erased as a prefix.
    matches = list(_LABEL.finditer(text))
    if len(matches) != 1:
        return None  # A second actual identifier is not discarded as a key.
    start, end = matches[0].start(), len(text.rstrip())
    return (start, end, text[start:end]) if legend_heading(text[start:end]) else None


def _window(line, size):
    box = line["bbox"]
    return [
        max(0, box[0] - 26),
        max(0, box[1] - 2),
        min(size[0], box[2] + 2),
        min(size[1], box[3] + 2),
    ]


def _point_box(box, bounds, dpi):
    origin = [
        math.floor((bounds[0] + 1.5) * dpi / 72) * 72 / dpi,
        math.floor((bounds[1] + 1.2) * dpi / 72) * 72 / dpi,
    ]
    return [v * 72 / dpi + origin[i % 2] for i, v in enumerate(box)]


def _separate(mask, bounds, dpi, height):
    columns = np.flatnonzero(mask.any(axis=0))
    if not len(columns):
        return None
    groups = np.split(columns, np.flatnonzero(np.diff(columns) > 1) + 1)
    if not 2 <= len(groups) <= 128:
        return None
    left, right = int(groups[0][0]), int(groups[0][-1]) + 1
    rows = np.flatnonzero(mask[:, left:right].any(axis=1))
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    if marker_extent(mask[top:bottom, left:right], dpi, height) is None:
        return None
    text_left, text_right = int(groups[1][0]), int(groups[-1][-1]) + 1
    text_rows = np.flatnonzero(mask[:, text_left:text_right].any(axis=1))
    text_box = [text_left, int(text_rows[0]), text_right, int(text_rows[-1]) + 1]
    # Every non-key ink pixel belongs to the one retained complete text window.
    # Neither a preferred word subset nor the compound number chooses the cut.
    return {
        "key": _point_box([left, top, right, bottom], bounds, dpi),
        "text": _point_box(text_box, bounds, dpi),
    }


def locator_nomination(packet, size):
    if not isinstance(packet, dict) or set(packet) != {
        "version",
        "source_line",
        "literal_range",
        "pixels",
    }:
        return None
    line = packet["source_line"]
    if (
        type(packet["version"]) is not int
        or packet["version"] != 1
        or not isinstance(line, dict)
        or set(line) != _LINE_FIELDS
        or line["source"] not in {"native", "page_ocr"}
        or line["geometry_space"] != "rendered"
        or not inside_box(line["bbox"], [0, 0, *size])
        or line["bbox"][3] - line["bbox"][1] > 32
    ):
        return None
    candidate = legend_candidate(line["text"])
    if candidate is None or (
        not isinstance(packet["literal_range"], list)
        or len(packet["literal_range"]) != 2
        or any(type(v) is not int for v in packet["literal_range"])
        or packet["literal_range"] != list(candidate[:2])
    ):
        return None
    bounds = _window(line, size)
    pixels = packet["pixels"]
    if (
        not isinstance(pixels, dict)
        or set(pixels) != {"bbox", "readings"}
        or pixels["bbox"] != bounds
        or not isinstance(pixels["readings"], list)
        or len(pixels["readings"]) != 2
    ):
        return None
    results = []
    for reading, dpi in zip(pixels["readings"], (400, 600)):
        mask = retained_pixels(reading, bounds, dpi, MAX_LOCATOR_PIXELS)
        if mask is None:
            return None
        split = _separate(mask, bounds, dpi, line["bbox"][3] - line["bbox"][1])
        if split is None:
            return None
        results.append(split)
    if any(
        abs(a - b) > 1.2
        for name in ("key", "text")
        for a, b in zip(results[0][name], results[1][name])
    ):
        return None
    text = [
        min(results[0]["text"][0], results[1]["text"][0]),
        min(results[0]["text"][1], results[1]["text"][1]),
        max(results[0]["text"][2], results[1]["text"][2]),
        max(results[0]["text"][3], results[1]["text"][3]),
    ]
    if not inside_box(text, bounds) or not overlaps(text, line["bbox"]):
        return None
    # Ink extents are not a font-line box. The common original-cell inset defines
    # the deterministic reading window around every retained text pixel; do not
    # relax the existing graphic-key predicate to accommodate a different frame.
    text = literal_bounds(text, size)
    if not inside_box(text, bounds):
        return None
    return {
        "text": candidate[2],
        "bbox": text,
        "source": line["source"],
        "geometry_space": "rendered",
    }


def observe_legend_locator(page, line, size):
    candidate = legend_candidate(line.get("text"))
    if candidate is None or not inside_box(line.get("bbox"), [0, 0, *size]):
        return None
    if line["bbox"][3] - line["bbox"][1] > 32:
        return None
    original = {key: line[key] for key in _LINE_FIELDS}
    packet = {
        "version": 1,
        "source_line": original,
        "literal_range": list(candidate[:2]),
        "pixels": observe_pixels(page, _window(original, size), MAX_LOCATOR_PIXELS),
    }
    return packet if locator_nomination(packet, size) is not None else None
