"""Bounded shaft/solid-head geometry, preserving every supporting source stroke."""

import math
from collections import defaultdict

from .reaction_heads import head_bounds

_GRID = 20


def filled_head_index(heads, indexes, tolerance):
    grid = defaultdict(list)
    for index in indexes:
        box = head_bounds(heads[index], padding=tolerance)
        if max(box[2] - box[0], box[3] - box[1]) > 40:
            # Not a qualified arrow head. The complete source observation is
            # still retained and tested as competing ink by both consumers.
            continue
        for x in range(math.floor(box[0] / _GRID), math.floor(box[2] / _GRID) + 1):
            for y in range(math.floor(box[1] / _GRID), math.floor(box[3] / _GRID) + 1):
                grid[(x, y)].append(index)
                if len(grid[(x, y)]) > 16:
                    raise ValueError("Ambiguous native filled-head neighborhood")
    return grid


def _on_edge(point, first, last, tolerance):
    dx, dy = last[0] - first[0], last[1] - first[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return False
    along = ((point[0] - first[0]) * dx + (point[1] - first[1]) * dy) / length
    across = abs((point[0] - first[0]) * dy - (point[1] - first[1]) * dx) / length
    return -tolerance <= along <= length + tolerance and across <= tolerance


def _outline_strokes(head, eligible, segments, tolerance):
    points = head["points"]
    return {
        i
        for i in eligible
        if any(
            _on_edge(segments[i][:2], first, last, tolerance)
            and _on_edge(segments[i][2:], first, last, tolerance)
            for first, last in zip(points, points[1:] + points[:1], strict=True)
        )
    }


def filled_arrows(shaft, end, tail, segments, heads, grid, eligible, tolerance):
    length = math.dist(end, tail)
    ux, uy = (end[0] - tail[0]) / length, (end[1] - tail[1]) / length
    arrows = []
    for index in grid.get((math.floor(end[0] / _GRID), math.floor(end[1] / _GRID)), ()):
        head = heads[index]
        projected = [
            (
                (p[0] - end[0]) * ux + (p[1] - end[1]) * uy,
                (p[0] - end[0]) * -uy + (p[1] - end[1]) * ux,
                p,
            )
            for p in head["points"]
        ]
        projected.sort(key=lambda value: value[0], reverse=True)
        apex, left, right = projected
        arms = [(apex[0] - base[0], base[1] - apex[1]) for base in (left, right)]
        if (
            abs(apex[1]) > tolerance
            or not -tolerance <= apex[0] <= min(a[0] for a in arms) + tolerance
            or arms[0][1] * arms[1][1] >= 0
            or any(
                not 1.5 <= math.hypot(along, side) <= min(18, length * 0.5)
                or not 0.35 <= along / math.hypot(along, side) <= 0.97
                or not 0.2 <= abs(side) / math.hypot(along, side) <= 0.94
                for along, side in arms
            )
            or not 0.5 <= math.hypot(*arms[0]) / math.hypot(*arms[1]) <= 2
        ):
            continue
        strokes = _outline_strokes(head, eligible, segments, tolerance)
        strokes.add(shaft)
        box = head_bounds(head, padding=2)
        arrows.append(
            {
                "tail": list(tail),
                "tip": list(apex[2]),
                "segments": sorted(strokes),
                "heads": [index],
                "bounds": [
                    min(box[0], tail[0] - 2),
                    min(box[1], tail[1] - 2),
                    max(box[2], tail[0] + 2),
                    max(box[3], tail[1] + 2),
                ],
            }
        )
    return arrows


def coalesce_arrow_ink(arrows, heads, tolerance):
    """An exact separately painted outline is the same ink, not a second role."""
    result = []
    for arrow in sorted(arrows, key=lambda a: not bool(a["heads"])):
        duplicate = None
        for existing in result:
            if not (
                math.dist(arrow["tail"], existing["tail"]) <= tolerance
                and math.dist(arrow["tip"], existing["tip"]) <= tolerance
                and existing["heads"]
            ):
                continue
            if not arrow["heads"] and set(arrow["segments"]) <= set(
                existing["segments"]
            ):
                duplicate = existing
                break
            if arrow["heads"] and all(
                sorted(heads[i]["points"])
                == sorted(heads[existing["heads"][0]]["points"])
                for i in arrow["heads"]
            ):
                duplicate = existing
                break
        if duplicate is None:
            result.append(arrow)
        else:
            duplicate["heads"] = sorted(set(duplicate["heads"] + arrow["heads"]))
            duplicate["segments"] = sorted(
                set(duplicate["segments"] + arrow["segments"])
            )
            duplicate["bounds"] = [
                min(duplicate["bounds"][0], arrow["bounds"][0]),
                min(duplicate["bounds"][1], arrow["bounds"][1]),
                max(duplicate["bounds"][2], arrow["bounds"][2]),
                max(duplicate["bounds"][3], arrow["bounds"][3]),
            ]
    return result
