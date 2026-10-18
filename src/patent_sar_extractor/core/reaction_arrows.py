"""Explicit open vector-arrow heads, not left/right or largest-figure ranking."""

import math
from collections import defaultdict

from .source_geometry import overlaps

JOIN_TOLERANCE = 0.3
MAX_ARROW_COUNT = 512


def segment_bounds(segment, padding=2):
    return [
        min(segment[0], segment[2]) - padding,
        min(segment[1], segment[3]) - padding,
        max(segment[0], segment[2]) + padding,
        max(segment[1], segment[3]) + padding,
    ]


def contained(inner, outer):
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _key(point):
    return tuple(math.floor(v / JOIN_TOLERANCE) for v in point)


def _head(shaft, tip, tail, neighbors, segments):
    length = math.dist(tip, tail)
    ux, uy = (tip[0] - tail[0]) / length, (tip[1] - tail[1]) / length
    arms = []
    for index, other in neighbors:
        if index == shaft:
            continue
        dx, dy = other[0] - tip[0], other[1] - tip[1]
        along, side = dx * ux + dy * uy, dx * -uy + dy * ux
        arm_length = math.hypot(dx, dy)
        if (
            1.5 <= arm_length <= min(18, length * 0.5)
            and -0.97 * arm_length <= along <= -0.35 * arm_length
            and 0.2 * arm_length <= abs(side) <= 0.94 * arm_length
        ):
            arms.append((index, arm_length, side))
    if len(arms) != 2 or arms[0][2] * arms[1][2] >= 0:
        return None
    if not 0.5 <= arms[0][1] / arms[1][1] <= 2:
        return None
    indexes = [shaft, arms[0][0], arms[1][0]]
    extents = [segment_bounds(segments[i]) for i in indexes]
    return {
        "tail": list(tail),
        "tip": list(tip),
        "segments": sorted(indexes),
        "bounds": [
            min(b[0] for b in extents),
            min(b[1] for b in extents),
            max(b[2] for b in extents),
            max(b[3] for b in extents),
        ],
    }


def vector_arrows(observation, protected_regions):
    """Every local visible arrow is retained, including reverse/dangling arrows."""
    segments = observation["segments"]
    eligible = []
    for index, segment in enumerate(segments):
        box = segment_bounds(segment, 0)
        if not any(contained(box, region) for region in protected_regions):
            eligible.append(index)
    grid = defaultdict(list)
    for index in eligible:
        for point, other in [
            (segments[index][:2], segments[index][2:]),
            (segments[index][2:], segments[index][:2]),
        ]:
            grid[_key(point)].append((index, point, other))
    arrows = []
    for index in eligible:
        segment = segments[index]
        if math.dist(segment[:2], segment[2:]) < 18:
            continue
        for tip, tail in [(segment[:2], segment[2:]), (segment[2:], segment[:2])]:
            x, y = _key(tip)
            neighbors = [
                (i, other)
                for kx in range(x - 1, x + 2)
                for ky in range(y - 1, y + 2)
                for i, point, other in grid.get((kx, ky), ())
                if math.dist(point, tip) <= JOIN_TOLERANCE
            ]
            if len(neighbors) > 8:
                raise ValueError("Ambiguous native arrow junction")
            arrow = _head(index, tip, tail, neighbors, segments)
            if arrow is None:
                continue
            if not contained(arrow["bounds"], observation["bounds"]):
                raise ValueError("Native arrow crosses the original declaration")
            if any(overlaps(arrow["bounds"], region) for region in protected_regions):
                raise ValueError("Native arrow overlaps an independently owned source")
            if any(overlaps(arrow["bounds"], b) for b in observation["blockers"]):
                raise ValueError("Native arrow contains unsupported or raster ink")
            if any(
                i not in arrow["segments"]
                and overlaps(arrow["bounds"], segment_bounds(segments[i]))
                for i in eligible
            ):
                raise ValueError("Native arrow has competing original strokes")
            arrows.append(arrow)
            if len(arrows) > MAX_ARROW_COUNT:
                raise ValueError("Native arrow count bound exceeded")
    return arrows
