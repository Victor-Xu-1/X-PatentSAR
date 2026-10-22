"""Complete open or solid graphic heads; no inferred PDF paint attributes."""

import math

import numpy as np


def _cross(first, last):
    return first[..., 0] * last[..., 1] - first[..., 1] * last[..., 0]


def triangle_depth(points, triangle):
    a, b, c = triangle
    orientation = np.sign(_cross(b - a, c - a))
    if not orientation:
        return np.full(len(points), -math.inf)
    return np.min(
        [
            orientation
            * _cross(last - first, points - first)
            / np.linalg.norm(last - first)
            for first, last in ((a, b), (b, c), (c, a))
        ],
        axis=0,
    )


def _valid_arms(tip, ends, length, scale, footprint, sign):
    sizes = [float(np.linalg.norm(end - tip)) for end in ends]
    return bool(
        min(sizes) > 0
        and 0.5 <= sizes[0] / sizes[1] <= 2
        and all(
            max(1.5 * scale, 3 * footprint) <= size <= min(18 * scale, length * 0.5)
            and -0.97 * size <= (end[0] - tip[0]) * sign <= -0.35 * size
            and 0.2 * size <= abs(end[1]) <= 0.94 * size
            for end, size in zip(ends, sizes, strict=True)
        )
    )


def _arm(t, s, selected):
    x, y = t[selected], s[selected]
    if len(x) < 3 or np.ptp(x) < 1:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    if not math.isfinite(slope) or abs(slope) < 0.15:
        return None
    return slope, intercept, float(x.min())


def _solid(mask, t, s, tip, *, sign, scale, footprint, centre, u, v):
    along = sign * t
    length = float(np.ptp(along))
    front = along > along.min() + length * 0.5
    ends = []
    for side in (-1, 1):
        selected = front & (side * s >= (side * s[front]).max() - footprint / 2)
        ends.append(
            np.array([float(np.mean(t[selected])), float(np.mean(s[selected]))])
        )
    if not _valid_arms(tip, ends, length, scale, footprint, sign):
        return None
    triangle = np.array([tip, *ends])
    physical = centre + triangle[:, :1] * u + triangle[:, 1:] * v
    x0, y0 = np.maximum(0, np.floor(physical.min(axis=0)).astype(int))
    x1, y1 = np.minimum(mask.shape[::-1], np.ceil(physical.max(axis=0)).astype(int) + 1)
    yy, xx = np.indices((y1 - y0, x1 - x0))
    points = np.column_stack((xx.ravel() + x0 + 0.5, yy.ravel() + y0 + 0.5))
    local = np.column_stack(((points - centre) @ u, (points - centre) @ v))
    interior = triangle_depth(local, triangle) > math.sqrt(2) * footprint
    if interior.sum() < max(4, math.ceil(4 * footprint * footprint)):
        return None
    if not np.all(mask[y0:y1, x0:x1].ravel()[interior]):
        return None
    return ends


def observe_head(mask, t, s, radius, *, sign, scale, footprint, centre, u, v):
    along = sign * t
    length = float(np.ptp(along))
    supported = along[np.abs(s) <= 0.75 * footprint]
    if not supported.size:
        return None
    # A fitted arm may nominate a junction but may not extrapolate a new tip
    # beyond original ink. The tip is supported by the actual centre-line pixels.
    tip = np.array([float(supported.max()) * sign, 0.0])
    ends = _solid(
        mask,
        t,
        s,
        tip,
        sign=sign,
        scale=scale,
        footprint=footprint,
        centre=centre,
        u=u,
        v=v,
    )
    if ends is not None:
        return {"tip": tip, "arms": ends, "filled": True}
    front = along > along.min() + length * 0.5
    arms = [
        _arm(along, s, front & (direction * s > radius + 0.25 * footprint))
        for direction in (-1, 1)
    ]
    if any(arm is None for arm in arms):
        return None
    tips = [-arm[1] / arm[0] for arm in arms]
    if (
        abs(tips[0] - tips[1]) > 2 * radius
        or abs(np.mean(tips) - along.max()) > 2 * radius
    ):
        return None
    ends = [np.array([end * sign, slope * end + offset]) for slope, offset, end in arms]
    return (
        {"tip": tip, "arms": ends, "filled": False}
        if _valid_arms(tip, ends, length, scale, footprint, sign)
        else None
    )
