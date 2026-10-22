"""Literal connected shaft/head geometry; never a molecule or product guess."""

import math

import numpy as np

from .raster_reaction_heads import observe_head, triangle_depth


def _line_distance(points, first, last):
    delta = last - first
    amount = np.clip((points - first) @ delta / (delta @ delta), 0, 1)
    return np.linalg.norm(points - first - amount[:, None] * delta, axis=1)


def component_segments(mask, scale, *, pixel_step, paint_support):
    """Account for EVERY nonwhite pixel by one shaft and its attached heads.

    Multiple heads are conserved, not ranked or discarded. Their directed graph
    will refuse a reversible route. Extra branches, broken shafts, wide objects
    and unaccounted pixels cannot become a direction observation.
    """
    y, x = np.nonzero(mask)
    if not 3 <= len(x) <= 100_000:
        return None
    points = np.column_stack((x + 0.5, y + 0.5))
    centre = points.mean(axis=0)
    values, axes = np.linalg.eigh(np.cov(points - centre, rowvar=False))
    if values[0] <= 0 or values[1] < 8 * values[0]:
        return None
    u = axes[:, 1]
    v = np.array([-u[1], u[0]])
    t, s = (points - centre) @ u, (points - centre) @ v
    length = float(np.ptp(t))
    if length < 18 * scale:
        return None
    information = max(1.0, pixel_step * scale)
    footprint = max(information, paint_support * scale)
    # Heads may extend almost halfway along a short shaft. A broad central
    # percentage band would incorrectly measure their wings as shaft width.
    # Measure the actual central source-pixel cross section; complete-shape,
    # continuous-stroke and both-resolution support still validate every pixel.
    middle = np.abs(t - (t.min() + t.max()) / 2) <= information / 2
    if not np.any(middle):
        return None
    offset = float((s[middle].min() + s[middle].max()) / 2)
    s = s - offset
    centre = centre + offset * v
    radius = float(np.ptp(s[middle]) / 2 + 0.75 * footprint)
    if not 0.2 <= radius <= 2 * scale + footprint:
        return None
    heads = [
        head
        for sign in (-1, 1)
        if (
            head := observe_head(
                mask,
                t,
                s,
                radius,
                sign=sign,
                scale=scale,
                footprint=information,
                centre=centre,
                u=u,
                v=v,
            )
        )
    ]
    if not heads:
        return None
    tips = sorted((head["tip"] for head in heads), key=lambda point: point[0])
    ends = [
        np.array([float(t.min() + radius / 2), 0.0]),
        np.array([float(t.max() - radius / 2), 0.0]),
    ]
    if len(heads) == 2:
        ends = tips
    else:
        ends[0 if tips[0][0] < np.mean(t) else 1] = tips[0]
    lines = [(ends[0], ends[1])]
    lines.extend(
        (head["tip"], end)
        for head in heads
        if not head["filled"]
        for end in head["arms"]
    )
    triangles = [
        np.array([head["tip"], *head["arms"]]) for head in heads if head["filled"]
    ]
    local = np.column_stack((t, s))
    distances = np.min([_line_distance(local, a, b) for a, b in lines], axis=0)
    for triangle in triangles:
        edges = np.min(
            [
                _line_distance(local, triangle[i], triangle[(i + 1) % 3])
                for i in range(3)
            ],
            axis=0,
        )
        edges[triangle_depth(local, triangle) >= 0] = 0
        distances = np.minimum(distances, edges)
    # Raster resampling may touch one source pixel in each axis at an oblique
    # join. This is the physical pixel-cell diagonal, not a discarded-ink budget.
    if np.any(distances > radius + math.sqrt(2) * footprint):
        return None
    # Every proposed stroke must in turn be continuously supported by original
    # ink. A nearby component, a broken line or an empty inferred arm cannot vote.
    for a, b in lines:
        count = max(2, math.ceil(float(np.linalg.norm(b - a)) * 2))
        samples = np.linspace(a, b, count)
        pixels = centre + samples[:, :1] * u + samples[:, 1:] * v
        ix, iy = np.floor(pixels[:, 0]).astype(int), np.floor(pixels[:, 1]).astype(int)
        support = math.ceil(information)
        for px, py in zip(ix, iy, strict=True):
            view = mask[
                max(0, py - support) : py + support + 1,
                max(0, px - support) : px + support + 1,
            ]
            if not view.size or not view.any():
                return None
    return {
        "segments": [
            [*(centre + a[0] * u + a[1] * v), *(centre + b[0] * u + b[1] * v)]
            for a, b in lines
        ],
        "filled_heads": [
            centre + triangle[:, :1] * u + triangle[:, 1:] * v for triangle in triangles
        ],
        "uncertainty": float((2 * radius + math.sqrt(2) * footprint) / scale),
    }
