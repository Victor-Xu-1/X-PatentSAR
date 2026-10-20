"""Original native paint envelopes, never OCR or font-metric shrink guesses."""

import math
import re
from collections import defaultdict

import fitz

_TILE = 64
_MAX_CANDIDATES = 200_000


def _box(value):
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(type(v) in {int, float} and math.isfinite(v) for v in value)
        and -1_000_000 <= min(value) <= max(value) <= 1_000_000
        and value[0] < value[2]
        and value[1] < value[3]
    )


def valid_native_paint(part):
    paint = part.get("native_paint")
    return (
        part.get("source") == "native"
        and isinstance(paint, dict)
        and set(paint) == {"version", "seqno", "bbox"}
        and type(paint.get("version")) is int
        and paint["version"] == 1
        and type(paint.get("seqno")) is int
        and 0 <= paint["seqno"] < 100_000
        and _box(paint.get("bbox"))
    )


def native_paint_within(part, bounds):
    """A complete paint envelope may prove padding, never a convenient subset."""
    if not valid_native_paint(part):
        return False
    box = part["native_paint"]["bbox"]
    return (
        bounds[0] <= box[0] < box[2] <= bounds[2]
        and bounds[1] <= box[1] < box[3] <= bounds[3]
    )


def native_paint_disjoint(part, bounds):
    """Whole original paint outside the cell proves metric-only overlap."""
    if not valid_native_paint(part):
        return False
    box = part["native_paint"]["bbox"]
    return min(box[2], bounds[2]) <= max(box[0], bounds[0]) or min(
        box[3], bounds[3]
    ) <= max(box[1], bounds[1])


def attach_native_paints(page, native):
    """Retain uniquely matched whole original text-paint bounds on native words.

    Metric and original word boxes are not changed. Trace word geometry only
    establishes membership; the potentially larger WHOLE paint envelope is the
    containment witness. Unknown, hidden, ambiguous or excessive sources supply
    no override. Original replay recomputes this from the same PDF.
    Existing paint-order visibility replay remains mandatory; this geometry
    envelope alone cannot certify that text has not been covered later.
    """
    traces, paints = page.get_texttrace(), page.get_bboxlog()
    if (
        len(traces) > 50_000
        or len(paints) > 100_000
        or sum(len(span.get("chars", ())) for span in traces) > 1_000_000
    ):
        raise ValueError("Original native paint inventory exceeds its bound")
    tiles = defaultdict(list)
    for index, token in enumerate(native):
        tiles[math.floor(token["x"] / _TILE), math.floor(token["y"] / _TILE)].append(
            index
        )
    witnesses = defaultdict(list)
    candidates = 0
    for span in traces:
        color, order = span.get("color"), span.get("seqno")
        if (
            type(order) is not int
            or not 0 <= order < len(paints)
            or not _box(span.get("bbox"))
            or not _box(paints[order][1])
        ):
            continue
        filled = (
            span.get("type") == 0
            and span.get("opacity") == 1
            and isinstance(color, tuple)
            and bool(color)
            and min(color) < 0.9
            and paints[order][0] == "fill-text"
        )
        chars = span.get("chars")
        if not isinstance(chars, tuple) or not 0 < len(chars) <= 16_384:
            continue
        try:
            text = "".join(chr(char[0]) for char in chars)
        except (TypeError, ValueError, IndexError):
            continue
        words = defaultdict(list)
        for match in re.finditer(r"\S+", text):
            boxes = [char[3] for char in chars[match.start() : match.end()]]
            if any(not _box(box) for box in boxes):
                continue
            word = fitz.Rect()
            for box in boxes:
                word |= fitz.Rect(box)
            words[match.group()].append(word * page.rotation_matrix)
        trace_box = list(fitz.Rect(span["bbox"]) * page.rotation_matrix)
        paint_box = list(fitz.Rect(paints[order][1]) * page.rotation_matrix)
        left, top, right, bottom = [math.floor(v / _TILE) for v in trace_box]
        if (right - left + 1) * (bottom - top + 1) > 4096:
            continue
        indices = (
            index
            for x in range(left, right + 1)
            for y in range(top, bottom + 1)
            for index in tiles.get((x, y), ())
        )
        for index in indices:
            candidates += 1
            if candidates > _MAX_CANDIDATES:
                raise ValueError(
                    "Original native paint associations exceed their bound"
                )
            token = native[index]
            if not (
                trace_box[0] <= token["x"] <= trace_box[2]
                and trace_box[1] <= token["y"] <= trace_box[3]
            ):
                continue
            for word in words.get(token["text"], ()):
                if word.contains(fitz.Point(token["x"], token["y"])):
                    # A filled/stroked artificial-bold pair is not just the
                    # smaller fill envelope. Hidden/nonopaque/outline companions
                    # remain ambiguity, never disappear to select a handy paint.
                    witnesses[index].append(
                        {"version": 1, "seqno": order, "bbox": paint_box}
                        if filled
                        else None
                    )
    for index, observed in witnesses.items():
        if len(observed) == 1 and observed[0] is not None:
            native[index]["native_paint"] = observed[0]
