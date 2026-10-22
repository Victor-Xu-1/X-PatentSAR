"""Visible source connections with explicit bounded coordinate uncertainty."""

import math

from .reaction_arrows import contained, segment_bounds
from .reaction_heads import head_bounds
from .source_geometry import overlaps


class MissingReactionEndpoint(ValueError):
    """No drawing intersects this complete visible ray; not an inferred link."""


def check_source_corridor(observation, owner, diagrams, protected, corridor):
    """Arrows, open ports and explicit additions share one ink-ownership check."""
    if any(
        overlaps(corridor, region) and not any(region == d["bbox"] for d in diagrams)
        for region in protected
    ):
        raise ValueError("Native arrow connection crosses an independent source")
    if any(
        overlaps(corridor, blocker)
        and not any(contained(blocker, d["bbox"]) for d in diagrams)
        and blocker not in owner.get("owned_blockers", [])
        for blocker in observation["blockers"]
    ):
        raise ValueError("Native arrow connection is blocked by source ink")
    if any(
        i not in owner["segments"]
        and overlaps(corridor, segment_bounds(segment))
        and not any(contained(segment_bounds(segment, 0), d["bbox"]) for d in diagrams)
        for i, segment in enumerate(observation["segments"])
    ):
        raise ValueError("Native arrow connection has competing source strokes")
    if any(
        i not in owner["heads"]
        and overlaps(corridor, head_bounds(head))
        and not any(contained(head_bounds(head), d["bbox"]) for d in diagrams)
        for i, head in enumerate(observation["filled_heads"])
    ):
        raise ValueError("Native arrow connection has competing filled source ink")


def _ray_span(point, direction, box):
    lower, upper = 0.0, math.inf
    for axis in range(2):
        if abs(direction[axis]) < 1e-9:
            if not box[axis] < point[axis] < box[axis + 2]:
                return None
            continue
        ends = [(box[axis + i] - point[axis]) / direction[axis] for i in (0, 2)]
        lower, upper = max(lower, min(ends)), min(upper, max(ends))
    return (lower, upper) if lower < upper else None


def _stable_time(point, direction, box, upper, error, rate):
    """Intersect the exact linear inequalities q(t)±(error+rate*t) in box."""
    lower = 0.0
    for axis in range(2):
        for sign, boundary in ((1, box[axis]), (-1, -box[axis + 2])):
            coefficient = sign * direction[axis] - rate
            value = boundary + error - sign * point[axis]
            if abs(coefficient) < 1e-12:
                if value >= 0:
                    return None
            elif coefficient > 0:
                lower = max(lower, value / coefficient)
            else:
                upper = min(upper, value / coefficient)
    return lower + min(0.5, (upper - lower) / 2) if 0 <= lower < upper else None


def visible_endpoint(point, direction, diagrams, length, *, error=0.0, source_bounds):
    window = _ray_span(point, direction, source_bounds)
    if (
        window is None
        or window[0] != 0
        or not math.isfinite(window[1])
        or type(error) not in {int, float}
        or not math.isfinite(error)
        or error < 0
        or not math.isfinite(length)
        or length <= 0
        or error
        and length < 4 * error
    ):
        raise ValueError("Original arrow lacks a bounded stable source corridor")
    entries = [
        (span[0], d)
        for d in diagrams
        if (span := _ray_span(point, direction, d["bbox"])) is not None
    ]
    entries.sort(key=lambda pair: pair[0])
    if not entries:
        raise MissingReactionEndpoint("Native arrow endpoint has no local drawing")
    if entries[0][0] <= 0 or len(entries) > 1 and entries[1][0] - entries[0][0] <= 0.5:
        raise ValueError("Native arrow endpoint has no unique local visible drawing")
    distance, diagram = entries[0]
    margin = 0.0
    if error:
        # If both shaft endpoints are within e, direction error is bounded by
        # 2e/(L-2e). Evaluate the growing cone at its actual robust target entry,
        # not an arbitrary maximum of one shaft length or a fixed5e shortcut.
        rate = 2 * error / (length - 2 * error)
        distance = _stable_time(
            point, direction, diagram["bbox"], window[1], error, rate
        )
        if distance is None:
            raise ValueError("Pixel arrow endpoint is not stable within its ink error")
        margin = error + rate * distance
        end = [point[i] + direction[i] * distance for i in range(2)]
        if not all(
            diagram["bbox"][i] + margin < end[i] < diagram["bbox"][i + 2] - margin
            for i in range(2)
        ):
            raise ValueError("Original arrow cone has no strict interior witness")
        for other in diagrams:
            if other["structure_id"] == diagram["structure_id"]:
                continue
            outer = [
                value + (-margin if index < 2 else margin)
                for index, value in enumerate(other["bbox"])
            ]
            rival = _ray_span(point, direction, outer)
            if rival is not None and rival[0] <= distance:
                raise ValueError("Pixel arrow endpoint has a possible rival drawing")
    end = [point[i] + direction[i] * distance for i in range(2)]
    return diagram["structure_id"], segment_bounds([*point, *end], 2 + margin)


def open_source_ray(point, direction, diagrams, length, *, error, source_bounds):
    """Record the SAME missing endpoint's bounded corridor, never choose a node.

    The finite source boundary is an observed limit, not a virtual continuation.
    A possible drawing inside the uncertainty cone stays ambiguous. Callers must
    independently check the same original protected regions/strokes/blockers.
    """
    window = _ray_span(point, direction, source_bounds)
    if (
        window is None
        or window[0] != 0
        or not math.isfinite(window[1])
        or not math.isfinite(length)
        or length <= 0
        or type(error) not in {int, float}
        or not math.isfinite(error)
        or error < 0
        or error
        and length < 4 * error
    ):
        raise ValueError("Open reaction endpoint has no complete stable source ray")
    margin = error + (2 * error / (length - 2 * error) * window[1] if error else 0)
    if any(
        _ray_span(
            point,
            direction,
            [
                value + (-margin if index < 2 else margin)
                for index, value in enumerate(diagram["bbox"])
            ],
        )
        is not None
        for diagram in diagrams
    ):
        raise ValueError("Open reaction ray has a possible source drawing")
    end = [point[i] + direction[i] * window[1] for i in range(2)]
    corridor = segment_bounds([*point, *end], 2 + margin)
    corridor = [
        max(corridor[0], source_bounds[0]),
        max(corridor[1], source_bounds[1]),
        min(corridor[2], source_bounds[2]),
        min(corridor[3], source_bounds[3]),
    ]
    return {
        "point": list(point),
        "direction": list(direction),
        "source_boundary": end,
        "coordinate_error": error,
        "boundary_margin": margin,
        "corridor": corridor,
    }
