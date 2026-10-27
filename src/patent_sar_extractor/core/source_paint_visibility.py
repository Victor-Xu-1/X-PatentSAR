"""Conservative original text visibility using paint order and actual stroke ink."""

from dataclasses import dataclass
from itertools import pairwise

from .source_geometry import overlaps


def _segment_hits(first, last, box, width):
    lower, upper = 0.0, 1.0
    for axis in range(2):
        start, delta = first[axis], last[axis] - first[axis]
        low, high = box[axis] - width / 2, box[axis + 2] + width / 2
        if abs(delta) < 1e-9:
            if not low <= start <= high:
                return False
        else:
            a, b = (low - start) / delta, (high - start) / delta
            lower, upper = max(lower, min(a, b)), min(upper, max(a, b))
    return lower <= upper


def source_stroke_hits(page, path, box):
    if path is None or path.get("stroke_opacity") != 1:
        return True
    width = path.get("width")
    if type(width) not in {int, float} or not 0 < width <= 100:
        return True
    segments = []
    for item in path["items"]:
        if item[0] == "l":
            segments.append((item[1], item[2]))
        elif item[0] == "re":
            rectangle = item[1]
            points = [
                rectangle.tl,
                rectangle.tr,
                rectangle.br,
                rectangle.bl,
                rectangle.tl,
            ]
            segments.extend(pairwise(points))
        elif item[0] == "qu":
            quad = item[1]
            points = [quad.ul, quad.ur, quad.lr, quad.ll, quad.ul]
            segments.extend(pairwise(points))
        else:
            return True  # Unknown curved stroke is not an empty bounding box.
    if path.get("closePath") and segments:
        segments.append((segments[-1][1], segments[0][0]))
    return any(
        _segment_hits(a * page.rotation_matrix, b * page.rotation_matrix, box, width)
        for a, b in segments
    )


@dataclass(frozen=True)
class NativePaintView:
    """Call-local immutable source facts, never serialized or globally cached."""

    owner: tuple
    visible: tuple
    paints: tuple
    paths: dict
    glyphs: dict


def _owner(page):
    return (
        id(page.parent),
        page.number,
        page.xref,
        page.rotation,
        tuple(page.rect),
        tuple(page.cropbox),
        tuple(page.get_contents()),
    )


def native_paint_view(page):
    """Observe the existing bounded paint inventory once for a read-only page."""
    import fitz

    from .source_paint_paths import original_path_owners

    traces, paints, drawings = (
        page.get_texttrace(),
        page.get_bboxlog(),
        page.get_drawings(),
    )
    if (
        len(traces) > 50000
        or sum(len(span.get("chars", ())) for span in traces) > 1_000_000
        or len(paints) > 100000
        or len(drawings) > 20000
    ):
        raise ValueError("Native heading paint inventory exceeds its bound")
    visible = []
    glyphs = {}
    for span in traces:
        color = span.get("color")
        if (
            span.get("type") not in {0, 1}
            or span.get("opacity") != 1
            or not isinstance(color, tuple)
            or not color
            or min(color) >= 0.9
        ):
            continue
        visible.append(
            (
                list(fitz.Rect(span["bbox"]) * page.rotation_matrix),
                "".join(chr(c[0]) for c in span["chars"]),
                span["seqno"],
            )
        )
        glyphs.setdefault(span["seqno"], []).extend(
            (
                chr(character[0]),
                list(fitz.Rect(character[3]) * page.rotation_matrix),
            )
            for character in span["chars"]
        )
    return NativePaintView(
        _owner(page),
        tuple(visible),
        tuple(paints),
        original_path_owners(paints, drawings),
        {order: tuple(characters) for order, characters in glyphs.items()},
    )


def original_paint_view(page, paint_view=None):
    """Only immutable facts for this exact original page may be reused."""
    # A writable/edited document cannot reuse a previous paint observation,
    # including in-place stream edits that leave the contents xref unchanged.
    # Normal original-file readers are immutable for this bounded call only.
    if paint_view is not None and (
        not isinstance(paint_view, NativePaintView) or paint_view.owner != _owner(page)
    ):
        return None
    if paint_view is None or page.parent.is_dirty:
        paint_view = native_paint_view(page)
    return paint_view


def visible_native_tokens(page, native, *, paint_view=None):
    import fitz

    paint_view = original_paint_view(page, paint_view)
    if paint_view is None:
        return False

    def covers(order, kind, bounds, box):
        if kind == "ignore-text" or not overlaps(
            list(fitz.Rect(bounds) * page.rotation_matrix), box
        ):
            return False
        if kind == "stroke-path":
            return source_stroke_hits(page, paint_view.paths.get(order), box)
        return True

    for token in native["tokens"]:
        witnesses = []
        for bounds, text, order in paint_view.visible:
            if not (
                bounds[0] <= token["x"] <= bounds[2]
                and bounds[1] <= token["y"] <= bounds[3]
                and token["text"] in text
            ):
                continue
            if not any(
                covers(i, kind, box, token["bbox"])
                for i, (kind, box) in enumerate(
                    paint_view.paints[order + 1 :], order + 1
                )
            ):
                witnesses.append(order)
        if not witnesses:
            return False
    return bool(native["tokens"])
