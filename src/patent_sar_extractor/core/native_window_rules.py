"""Original axial rule paths subordinate to the existing closed-cell pixel proof."""

from itertools import pairwise

from .source_geometry import overlaps


def original_rule_path(path, page):
    """Retain complete simple source paths; unknown paint is never a rule vote."""
    if not isinstance(path, dict) or not (
        path.get("type") == "s"
        and path.get("stroke_opacity") == 1
        and path.get("fill") is None
        and isinstance(path.get("color"), tuple)
        and path["color"]
        and min(path["color"]) >= 0
        and max(path["color"]) <= 0.45
        and type(path.get("width")) in {int, float}
        and 0 < path["width"] <= 4
        and path.get("dashes") == "[] 0"
        and 0 < len(path.get("items", [])) <= 4096
    ):
        return None
    segments = []
    for item in path["items"]:
        if item[0] == "l":
            segments.append((item[1], item[2]))
        elif item[0] == "re":
            rectangle = item[1]
            segments.extend(
                pairwise(
                    [
                        rectangle.tl,
                        rectangle.tr,
                        rectangle.br,
                        rectangle.bl,
                        rectangle.tl,
                    ]
                )
            )
        else:
            return None
    if path.get("closePath") and segments:
        segments.append((segments[-1][1], segments[0][0]))
    return {
        "width": path["width"],
        "segments": [
            [*(first * page.rotation_matrix), *(last * page.rotation_matrix)]
            for first, last in segments
        ],
    }


def boundary_rule_path(path, bounds):
    """Geometry alone grants nothing: the caller also needs all four pixel edges."""
    import math

    if not isinstance(path, dict) or set(path) != {"width", "segments"}:
        return False
    width, segments = path["width"], path["segments"]
    if (
        type(width) not in {int, float}
        or not math.isfinite(width)
        or not 0 < width <= 4
        or not isinstance(segments, list)
        or not 0 < len(segments) <= 16385
    ):
        return False
    touched = False
    for segment in segments:
        if (
            not isinstance(segment, list)
            or len(segment) != 4
            or any(type(v) not in {int, float} or not math.isfinite(v) for v in segment)
        ):
            return False
        x0, y0, x1, y1 = segment
        box = [
            min(x0, x1) - width / 2,
            min(y0, y1) - width / 2,
            max(x0, x1) + width / 2,
            max(y0, y1) + width / 2,
        ]
        if not overlaps(box, bounds):
            continue
        touched = True
        # One pixel of the existing 240dpi grid locator, not an erased inset.
        if not (
            x0 == x1
            and min(abs(x0 - bounds[0]), abs(x0 - bounds[2])) <= 72 / 240
            or y0 == y1
            and min(abs(y0 - bounds[1]), abs(y0 - bounds[3])) <= 72 / 240
        ):
            return False
    return touched
