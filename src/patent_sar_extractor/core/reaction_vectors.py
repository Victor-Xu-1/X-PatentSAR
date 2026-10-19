"""Bounded native vector observations in the original rendered PDF frame.

Unsupported curves/fills, clipping, raster ink and text remain blockers. This
reader neither recognizes chemistry nor assigns a compound or reaction role.
"""

import math
from itertools import pairwise

from .reaction_heads import MAX_FILLED_HEADS, observe_triangle, validate_heads
from .source_geometry import overlaps

MAX_VECTOR_SEGMENTS = 20000
MAX_VECTOR_BLOCKERS = 10000


def valid_rectangle(value, size):
    return bool(
        isinstance(value, list)
        and len(value) == 4
        and all(type(v) in {int, float} and math.isfinite(v) for v in value)
        and 0 <= value[0] < value[2] <= size[0]
        and 0 <= value[1] < value[3] <= size[1]
    )


def validate_vectors(observation):
    if not isinstance(observation, dict) or set(observation) != {
        "version",
        "page_no",
        "page_size",
        "bounds",
        "segments",
        "filled_heads",
        "blockers",
    }:
        raise ValueError("Malformed native reaction observation")
    size = observation["page_size"]
    if (
        type(observation["version"]) is not int
        or observation["version"] != 2
        or type(observation["page_no"]) is not int
        or not 1 <= observation["page_no"] <= 20000
        or not isinstance(size, list)
        or len(size) != 2
        or not all(
            type(v) in {int, float} and math.isfinite(v) and 0 < v <= 100000
            for v in size
        )
        or not valid_rectangle(observation["bounds"], size)
        or not isinstance(observation["segments"], list)
        or len(observation["segments"]) > MAX_VECTOR_SEGMENTS
        or not isinstance(observation["blockers"], list)
        or len(observation["blockers"]) > MAX_VECTOR_BLOCKERS
    ):
        raise ValueError("Native reaction observation exceeds its source bounds")
    for segment in observation["segments"]:
        if (
            not isinstance(segment, list)
            or len(segment) != 4
            or not all(type(v) in {int, float} and math.isfinite(v) for v in segment)
            or not all(0 <= segment[i] <= size[i % 2] for i in range(4))
            or segment[:2] == segment[2:]
        ):
            raise ValueError("Malformed native reaction segment")
    if any(not valid_rectangle(box, size) for box in observation["blockers"]):
        raise ValueError("Malformed native reaction blocker")
    validate_heads(observation["filled_heads"], size)


def observe_vectors(page, bounds):
    """Read current original paths once; never substitute raster absence for proof."""
    import fitz

    size = [page.rect.width, page.rect.height]
    if not valid_rectangle(bounds, size):
        raise ValueError("Invalid native reaction source window")
    segments, blockers, heads = [], [], []

    def block(rectangle):
        box = (fitz.Rect(rectangle) * page.rotation_matrix) & page.rect
        # Only degenerate line extents need padding. Raster/text bounds remain
        # exact, so native arrows may legitimately connect raster molecules.
        if box.width == 0:
            box.x0, box.x1 = box.x0 - 0.5, box.x1 + 0.5
        if box.height == 0:
            box.y0, box.y1 = box.y0 - 0.5, box.y1 + 0.5
        box &= page.rect
        value = list(box)
        if valid_rectangle(value, size) and overlaps(value, bounds):
            blockers.append(value)
        if len(blockers) > MAX_VECTOR_BLOCKERS:
            raise ValueError("Native reaction blocker bound exceeded")

    paths = page.get_drawings(extended=True)
    if len(paths) > MAX_VECTOR_SEGMENTS:
        raise ValueError("Native reaction path bound exceeded")
    for path in paths:
        items, color = path.get("items", []), path.get("color")
        triangle = observe_triangle(path, page.rotation_matrix)
        if triangle is not None:
            from .reaction_heads import head_bounds

            if overlaps(head_bounds(triangle), bounds):
                heads.append(triangle)
                if len(heads) > MAX_FILLED_HEADS:
                    raise ValueError("Native filled-head source bound exceeded")
            continue
        plain = (
            path.get("type") == "s"
            and path.get("stroke_opacity") == 1
            and isinstance(color, tuple)
            and color
            and max(color) <= 0.45
            and 0 < path.get("width", 0) <= 4
            and path.get("dashes") == "[] 0"
            and items
            and all(item[0] == "l" for item in items)
        )
        if not plain:
            block(path.get("rect") or page.rect)
            continue
        observed_lines = list(items)
        if path.get("closePath"):
            if any(
                math.dist(left[2], right[1]) > 1e-6 for left, right in pairwise(items)
            ):
                block(path.get("rect") or page.rect)
                continue
            observed_lines.append(("l", items[-1][2], items[0][1]))
        for _, first, last in observed_lines:
            a, b = first * page.rotation_matrix, last * page.rotation_matrix
            if a == b:
                continue
            # Keep whole segments crossing the window, not shortened arrow ends.
            extent = [
                min(a.x, b.x) - 2,
                min(a.y, b.y) - 2,
                max(a.x, b.x) + 2,
                max(a.y, b.y) + 2,
            ]
            if overlaps(extent, bounds):
                segments.append([a.x, a.y, b.x, b.y])
            if len(segments) > MAX_VECTOR_SEGMENTS:
                raise ValueError("Native reaction segment bound exceeded")
    words, images = page.get_text("words"), page.get_image_info()
    if len(words) > 50000 or len(images) > 4096:
        raise ValueError("Native reaction original layout bound exceeded")
    for word in words:
        block(word[:4])
    for image in images:
        block(image["bbox"])
    observation = {
        "version": 2,
        "page_no": page.number + 1,
        "page_size": size,
        "bounds": list(bounds),
        "segments": segments,
        "filled_heads": heads,
        "blockers": blockers,
    }
    validate_vectors(observation)
    return observation
