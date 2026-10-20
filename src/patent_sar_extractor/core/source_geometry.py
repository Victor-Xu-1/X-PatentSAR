"""Call-local original native/raster ownership in the rendered PDF point frame.

No OCR engine, scientific interpretation, persistent cache or artifact writer.
Native text remains separate evidence when raster pixels own layout discovery.
"""

import math
from dataclasses import dataclass

from .source_cell_tokens import cell_text


def _box(value):
    import fitz

    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
    ):
        raise ValueError("Invalid original source geometry")
    rectangle = fitz.Rect(value)
    if rectangle.is_empty or rectangle.is_infinite:
        raise ValueError("Empty original source geometry")
    return rectangle


def overlaps(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def owned(tokens, bounds):
    x0, y0, x1, y1 = bounds
    return [t for t in tokens if x0 <= t["x"] < x1 and y0 <= t["y"] < y1]


@dataclass(frozen=True)
class SourceLayout:
    native: tuple[dict, ...]
    raster_bounds: tuple[float, float, float, float] | None


def source_layout(page) -> SourceLayout:
    import fitz

    words = page.get_text("words")
    images = page.get_image_info()
    if len(words) > 50000 or len(images) > 4096:
        raise ValueError("Original source layout exceeds its page resource bound")
    native = []
    for word in words:
        original = _box(list(word[:4]))
        rendered = original * page.rotation_matrix
        native.append(
            {
                "text": word[4],
                "x": (rendered.x0 + rendered.x1) / 2,
                "y": (rendered.y0 + rendered.y1) / 2,
                "bbox": list(rendered),
                "original_bbox": list(original),
                "confidence": 1.0,
                "source": "native",
                "geometry_space": "rendered",
                "line": list(word[5:7]),
            }
        )
    from .native_paint_geometry import attach_native_paints

    attach_native_paints(page, native)
    union = fitz.Rect()
    for image in images:
        rectangle = (_box(list(image["bbox"])) * page.rotation_matrix) & page.rect
        if not rectangle.is_empty:
            union |= rectangle
    return SourceLayout(tuple(native), tuple(union) if not union.is_empty else None)


class SourceTokens(list):
    """One layout list plus original independent native evidence for cell proof."""

    def __init__(self, tokens, layout: SourceLayout, scan_bounds=None):
        super().__init__(tokens)
        self.native_tokens = layout.native
        self.scan_bounds = scan_bounds
        self.geometry_space = "rendered"
        self.native_paint_view = None  # Call-local original facts, never evidence JSON.


def native_region(tokens, bounds, fallback: bool) -> bool:
    if not isinstance(tokens, SourceTokens):
        # Caller-supplied legacy observations retain their explicit contract;
        # every current original-page producer supplies SourceTokens instead.
        return fallback
    return bool(owned(tokens.native_tokens, bounds)) and not (
        tokens.scan_bounds is not None and overlaps(tokens.scan_bounds, bounds)
    )


def native_cell_text(tokens, bounds) -> str:
    if not isinstance(tokens, SourceTokens):
        return ""
    return cell_text(tokens.native_tokens, bounds)


def token_geometry_space(tokens, native: bool) -> str:
    return (
        tokens.geometry_space
        if isinstance(tokens, SourceTokens)
        else "unrotated"
        if native
        else "rendered"
    )


def native_lines(layout: SourceLayout, exclude=None) -> list[dict]:
    groups = {}
    for token in layout.native:
        if exclude is not None and overlaps(token["bbox"], exclude):
            continue
        groups.setdefault(tuple(token["line"]), []).append(token)
    output = []
    for group in groups.values():
        bbox = [
            min(t["bbox"][0] for t in group),
            min(t["bbox"][1] for t in group),
            max(t["bbox"][2] for t in group),
            max(t["bbox"][3] for t in group),
        ]
        output.append(
            {
                "y0": bbox[1],
                "text": " ".join(t["text"] for t in group),
                "bbox": bbox,
                "source": "native",
                "geometry_space": "rendered",
            }
        )
    return sorted(output, key=lambda line: (line["y0"], line["bbox"][0]))
