"""Original opaque triangular fill observations, not chemical wedge semantics."""

import math

MAX_FILLED_HEADS = 2048


def _dark(color):
    return (
        isinstance(color, (list, tuple))
        and len(color) == 3
        and all(
            type(v) in {int, float} and math.isfinite(v) and 0 <= v <= 0.45
            for v in color
        )
    )


def head_bounds(head, *, padding=0):
    points = head["points"]
    pad = padding + head["stroke_width"] / 2
    return [
        min(p[0] for p in points) - pad,
        min(p[1] for p in points) - pad,
        max(p[0] for p in points) + pad,
        max(p[1] for p in points) + pad,
    ]


def validate_heads(heads, size):
    if not isinstance(heads, list) or len(heads) > MAX_FILLED_HEADS:
        raise ValueError("Native filled-head inventory exceeds its bound")
    for head in heads:
        if (
            not isinstance(head, dict)
            or set(head) != {"points", "stroke_width", "fill_color", "stroke_color"}
            or not isinstance(head["points"], list)
            or len(head["points"]) != 3
            or any(
                not isinstance(p, list)
                or len(p) != 2
                or any(type(v) not in {int, float} or not math.isfinite(v) for v in p)
                or not all(0 <= p[i] <= size[i] for i in range(2))
                for p in head["points"]
            )
            or type(head["stroke_width"]) not in {int, float}
            or not math.isfinite(head["stroke_width"])
            or not 0 <= head["stroke_width"] <= 4
            or not _dark(head["fill_color"])
            or (
                head["stroke_color"] is None
                and head["stroke_width"] != 0
                or head["stroke_color"] is not None
                and (not _dark(head["stroke_color"]) or head["stroke_width"] == 0)
            )
        ):
            raise ValueError("Malformed native filled-head observation")
        a, b, c = head["points"]
        if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) <= 0.2:
            raise ValueError("Native filled head has no resolved triangular area")


def observe_triangle(path, rotation):
    """Conserve only a literal opaque three-vertex fill and its actual outline.

    PDF fill closes an otherwise open polygon implicitly. Curves, holes, extra
    vertices, unknown clipping and translucent/unsupported outlines are not
    simplified into an arrow. Role classification happens outside this reader.
    """
    stroked = path.get("type") == "fs"
    if (
        path.get("type") not in {"f", "fs"}
        or path.get("fill_opacity") != 1
        or not _dark(path.get("fill"))
        or not path.get("items")
        or not all(item[0] == "l" for item in path["items"])
        or (
            stroked
            and (
                path.get("stroke_opacity") != 1
                or not _dark(path.get("color"))
                or type(path.get("width")) not in {int, float}
                or not 0 < path["width"] <= 4
                or path.get("dashes") != "[] 0"
            )
        )
    ):
        return None
    points = []
    for _, first, last in path["items"]:
        if points and math.dist(points[-1], first) > 1e-6:
            return None
        if not points:
            points.append(first)
        points.append(last)
    if math.dist(points[0], points[-1]) <= 1e-6:
        points.pop()
    if len(points) != 3:
        return None
    return {
        "points": [list(point * rotation) for point in points],
        "stroke_width": path["width"] if stroked else 0,
        "fill_color": list(path["fill"]),
        "stroke_color": list(path["color"]) if stroked else None,
    }
