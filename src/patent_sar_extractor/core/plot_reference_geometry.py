"""Original quantitative-axis and legend nomination; no molecular ownership."""

import math
import re
from itertools import chain, pairwise

from .cell_frame_proof import inside_box
from .compound_caption import caption_identity
from .source_geometry import overlaps
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


def context_bounds(caption, axes, label, size, *, row_bounds=None, locator_bounds=None):
    boxes = [
        caption["bbox"],
        label,
        marker_bounds(label, size),
        *(p["bbox"] for group in axes.values() for p in group),
        *axis_bounds(axes).values(),
        *([row_bounds] if row_bounds is not None else []),
        *([locator_bounds] if locator_bounds is not None else []),
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


def _aligned_groups(parts, axis):
    """Conserve complete edge-aligned families, not convenient numeric subsets.

    Rotated labels with different lengths need not have aligned centres. Their
    original top/bottom (or left/right) edges still nominate one literal family.
    Overlapping nominations are joined before checking numerical order, so a
    contradictory member cannot disappear by choosing another anchor/edge.
    """
    groups = []
    for position in (axis, axis + 2, None):
        coordinates = [
            p["bbox"][position] if position is not None else sum(p["bbox"][axis::2]) / 2
            for p in parts
        ]
        for coordinate in coordinates:
            group = {
                i for i, value in enumerate(coordinates) if abs(value - coordinate) <= 3
            }
            for previous in groups[:]:
                if group & previous:
                    group |= previous
                    groups.remove(previous)
            groups.append(group)
    return [[parts[i] for i in sorted(group)] for group in groups]


def _complete_axis(parts, tokens, independent_tokens, alignment_axis, *, before=None):
    # An unread first/last member can be outside the numeric envelope. Reuse the
    # same complete physical alignment families for both observed origins before
    # checking literals; the successful numeric subset cannot choose its bounds.
    low = min(p["bbox"][alignment_axis] for p in parts) - 3
    high = max(p["bbox"][alignment_axis + 2] for p in parts) + 3
    order_axis = 1 - alignment_axis
    nearby = [
        token
        for token in chain(tokens, independent_tokens)
        if token["text"].strip()
        and token["bbox"][alignment_axis] <= high
        and token["bbox"][alignment_axis + 2] >= low
        and (before is None or token["bbox"][order_axis + 2] < before)
    ]
    if len(nearby) > 256:
        return False  # Excess original inventory is not a successful prefix.
    seeds = {id(part) for part in parts}
    families = (
        group
        for group in _aligned_groups([*parts, *nearby], alignment_axis)
        if any(id(part) in seeds for part in group)
    )
    return all(
        any(
            literal(token["text"]) == literal(part["text"])
            and overlaps(token["bbox"], part["bbox"])
            for part in parts
        )
        for token in chain.from_iterable(families)
    )


def _axis_candidates(tokens, caption, label, size, independent_tokens, *, unread=False):
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
    row_members = numbers
    if unread:
        row_members = [
            p
            for p in tokens
            if isinstance(p.get("text"), str)
            and p["text"].strip()
            and inside_box(p.get("bbox"), [0, 0, *size])
            and label[3] + 2 < p["bbox"][1] < label[3] + 360
        ]
        if len(row_members) > 256:
            return None
    candidates = {}
    for row in _aligned_groups(row_members, 1):
        xs = (
            [source_literal(p) for p in sorted(row, key=lambda p: sum(p["bbox"][::2]))]
            if unread and 3 <= len(row) <= 32
            else _ordered(row, 0)
            if not unread
            else None
        )
        if (
            xs is None
            or not unread
            and not _complete_axis(xs, tokens, independent_tokens, 1)
        ):
            continue
        left, right = xs[0]["bbox"], xs[-1]["bbox"]
        span = (right[0] + right[2] - left[0] - left[2]) / 2
        if span < 45:
            continue
        above = [p for p in numbers if p["bbox"][3] < min(x["bbox"][1] for x in xs)]
        for column in _aligned_groups(above, 0):
            ys = _ordered(column, 1)
            if (
                ys is None
                # Preserve the existing cross-axis boundary: later aligned
                # synthesis text is not a member of this vertical tick column.
                or not _complete_axis(
                    ys,
                    tokens,
                    independent_tokens,
                    0,
                    before=min(p["bbox"][1] for p in xs),
                )
                or ys[-1]["bbox"][1] - ys[0]["bbox"][1] < 40
            ):
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


def plot_axes(tokens, caption, label, size, *, independent_tokens=()):
    return _axis_candidates(tokens, caption, label, size, independent_tokens)


def plot_axis_nomination(tokens, caption, label, size, *, independent_tokens=()):
    """Original geometry only; unread words require bounded original-image proof."""
    return _axis_candidates(
        tokens, caption, label, size, independent_tokens, unread=True
    )
