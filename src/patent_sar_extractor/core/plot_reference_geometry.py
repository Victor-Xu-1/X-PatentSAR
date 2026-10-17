"""Original quantitative-axis and legend nomination; no molecular ownership."""

import math
import re
from itertools import pairwise

from .cell_frame_proof import inside_box
from .compound_caption import caption_identity
from .source_section_roles import section_heading

_FIGURE = re.compile(
    r"(?:fig(?:ure)?\.?\s*)(?P<identity>\d{1,6}(?:\s*[A-Z]|\s*\([A-Z]\))?)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?%?")


def literal(text):
    figure = _FIGURE.fullmatch(text.strip())
    if figure:
        return "figure:" + re.sub(r"[\s()]", "", figure["identity"]).casefold()
    return " ".join(text.split()).casefold()


def figure_caption(text):
    return isinstance(text, str) and bool(_FIGURE.fullmatch(text.strip()))


def legend_heading(text):
    observed = section_heading(text)
    return bool(
        observed
        and observed["role"] == "compound_heading"
        and observed["label_kind"] in {"compound", "cmpd", "cpd", "化合物"}
        and caption_identity(text)[0]
    )


def tick_value(text):
    if not isinstance(text, str) or len(text) > 64:
        return None
    raw = text.strip().replace("−", "-")
    if not _NUMBER.fullmatch(raw):
        return None
    value = float(raw.rstrip("%"))
    return value if math.isfinite(value) else None


def source_literal(part):
    return {"text": part["text"], "bbox": list(part["bbox"])}


def literal_bounds(box, size):
    # Cancel only the shared cell renderer's rule inset, not neighbouring ink.
    return [
        max(0, box[0] - 1.5),
        max(0, box[1] - 1.2),
        min(size[0], box[2] + 1.5),
        min(size[1], box[3] + 1.2),
    ]


def marker_bounds(box, size):
    return [
        max(0, box[0] - 26),
        max(0, box[1] - 0.5),
        max(0, box[0] - 3),
        min(size[1], box[3] + 0.5),
    ]


def context_bounds(caption, axes, label, size):
    boxes = [
        caption["bbox"],
        label,
        marker_bounds(label, size),
        *(p["bbox"] for group in axes.values() for p in group),
        *axis_bounds(axes).values(),
    ]
    return [
        max(0, min(b[0] for b in boxes) - 3),
        max(0, min(b[1] for b in boxes) - 3),
        min(size[0], max(b[2] for b in boxes) + 3),
        min(size[1], max(b[3] for b in boxes) + 3),
    ]


def axis_bounds(axes):
    xs, ys = axes["x"], axes["y"]
    first_x = sum(xs[0]["bbox"][::2]) / 2
    last_x = sum(xs[-1]["bbox"][::2]) / 2
    tick_top = min(p["bbox"][1] for p in xs)
    return {
        "x": [first_x - 12, ys[-1]["bbox"][3] + 2, last_x + 12, tick_top - 1],
        "y": [
            max(p["bbox"][2] for p in ys) + 2,
            ys[0]["bbox"][1] - 12,
            first_x + 12,
            tick_top - 1,
        ],
    }


def _ordered(parts, axis):
    parts = sorted(parts, key=lambda p: sum(p["bbox"][axis::2]))
    if not 3 <= len(parts) <= 32:
        return None
    values = [tick_value(p["text"]) for p in parts]
    differences = [b - a for a, b in pairwise(values)]
    if not (all(v > 0 for v in differences) or all(v < 0 for v in differences)):
        return None
    return [source_literal(p) for p in parts]


def plot_axes(tokens, caption, label, size):
    """Two independently ordered numeric axes, not a nearby Figure-word guess.

    This nominates original windows only. All selected literals and the graphic
    key still require original observations; no plotted activity is calculated.
    """
    if not figure_caption(caption.get("text")) or not inside_box(label, [0, 0, *size]):
        return None
    numbers = []
    seen = set()
    for token in tokens:
        box = token.get("bbox")
        if tick_value(token.get("text")) is None or not inside_box(box, [0, 0, *size]):
            continue
        if abs((box[1] + box[3]) / 2 - label[1]) > 360:
            continue
        key = (token["text"], tuple(box))
        if key not in seen:
            numbers.append(token)
            seen.add(key)
    if len(numbers) > 256:
        return None
    candidates = {}
    for anchor in numbers:
        row = [
            p
            for p in numbers
            if abs(sum(p["bbox"][1::2]) - sum(anchor["bbox"][1::2])) <= 6
        ]
        xs = _ordered(row, 0)
        if xs is None:
            continue
        left, right = xs[0]["bbox"], xs[-1]["bbox"]
        span = (right[0] + right[2] - left[0] - left[2]) / 2
        if span < 45:
            continue
        for head in numbers:
            column = [
                p
                for p in numbers
                if p["bbox"][3] < min(x["bbox"][1] for x in xs)
                and (
                    abs(p["bbox"][0] - head["bbox"][0]) <= 3
                    or abs(p["bbox"][2] - head["bbox"][2]) <= 3
                )
            ]
            ys = _ordered(column, 1)
            if ys is None or ys[-1]["bbox"][1] - ys[0]["bbox"][1] < 40:
                continue
            edge = max(p["bbox"][2] for p in ys)
            cap = caption["bbox"]
            if not (
                -4 <= (left[0] + left[2]) / 2 - edge <= 48
                and 0 < min(p["bbox"][1] for p in xs) - ys[-1]["bbox"][3] <= 80
                and ys[0]["bbox"][1] - 20 <= label[1] < label[3] <= ys[-1]["bbox"][3]
                and edge + 3 < label[0] < label[2] <= right[2] + span
                and min(p["bbox"][0] for p in ys)
                <= (cap[0] + cap[2]) / 2
                <= max(right[2], label[2])
                and (
                    cap[3] < ys[0]["bbox"][1] or cap[1] > max(p["bbox"][3] for p in xs)
                )
            ):
                continue
            axes = {"x": xs, "y": ys}
            key = tuple(
                (p["text"], tuple(p["bbox"])) for group in axes.values() for p in group
            )
            candidates[key] = axes
    return next(iter(candidates.values())) if len(candidates) == 1 else None
