"""Conservative original text visibility using paint order and actual stroke ink."""

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


def _stroke_hits(page, path, box):
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


def visible_native_tokens(page, native):
    import fitz

    traces, paints, drawings = (
        page.get_texttrace(),
        page.get_bboxlog(),
        page.get_drawings(),
    )
    if len(traces) > 50000 or len(paints) > 100000 or len(drawings) > 20000:
        raise ValueError("Native heading paint inventory exceeds its bound")
    paths = {path["seqno"]: path for path in drawings}

    def covers(order, kind, bounds, box):
        if kind == "ignore-text" or not overlaps(
            list(fitz.Rect(bounds) * page.rotation_matrix), box
        ):
            return False
        if kind == "stroke-path":
            return _stroke_hits(page, paths.get(order), box)
        return True

    visible = []
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
    for token in native["tokens"]:
        witnesses = []
        for bounds, text, order in visible:
            if not (
                bounds[0] <= token["x"] <= bounds[2]
                and bounds[1] <= token["y"] <= bounds[3]
                and token["text"] in text
            ):
                continue
            if not any(
                covers(i, kind, box, token["bbox"])
                for i, (kind, box) in enumerate(paints[order + 1 :], order + 1)
            ):
                witnesses.append(order)
        if not witnesses:
            return False
    return bool(native["tokens"])
