"""Visible source connections with explicit bounded coordinate uncertainty."""

import math

from .reaction_arrows import segment_bounds


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
    if (
        not entries
        or entries[0][0] <= 0
        or len(entries) > 1
        and entries[1][0] - entries[0][0] <= 0.5
    ):
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
