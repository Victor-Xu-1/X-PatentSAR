"""Bounded raster stroke observations, not an image-to-molecular-graph parser."""

from __future__ import annotations

from itertools import pairwise

import numpy as np


def thin_ink(ink: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning with fixed work limits and no optional CV dependency."""
    pixels = np.pad(ink.astype(np.uint8), 1)
    for _ in range(128):
        removed = 0
        for step in (0, 1):
            p = [
                pixels[:-2, 1:-1],
                pixels[:-2, 2:],
                pixels[1:-1, 2:],
                pixels[2:, 2:],
                pixels[2:, 1:-1],
                pixels[2:, :-2],
                pixels[1:-1, :-2],
                pixels[:-2, :-2],
            ]
            count = sum(p)
            transitions = sum((p[i] == 0) & (p[(i + 1) % 8] == 1) for i in range(8))
            if step == 0:
                empty = (p[0] * p[2] * p[4] == 0) & (p[2] * p[4] * p[6] == 0)
            else:
                empty = (p[0] * p[2] * p[6] == 0) & (p[0] * p[4] * p[6] == 0)
            delete = (
                (pixels[1:-1, 1:-1] == 1)
                & (count >= 2)
                & (count <= 6)
                & (transitions == 1)
                & empty
            )
            removed += int(np.count_nonzero(delete))
            pixels[1:-1, 1:-1][delete] = 0
        if removed == 0:
            return pixels[1:-1, 1:-1].astype(bool)
    raise ValueError("Stroke thinning exceeded its work limit")


def stroke_paths(skeleton: np.ndarray) -> list[np.ndarray]:
    """Trace owned strokes/cycle windows; suppress diagonal corner shortcuts."""
    locations = np.argwhere(skeleton)
    if len(locations) > 24000:
        raise ValueError("Source diagram exceeds the stroke budget")
    points = {(int(y), int(x)) for y, x in locations}
    neighbors: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for y, x in points:
        linked = []
        for dy, dx in (
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
        ):
            target = (y + dy, x + dx)
            if target not in points:
                continue
            if dy and dx and ((y, x + dx) in points or (y + dy, x) in points):
                continue
            linked.append(target)
        neighbors[(y, x)] = linked
    visited: set[frozenset[tuple[int, int]]] = set()
    paths = []
    # Observe branch paths first, then any remaining degree-two closed contour.
    # Both use the same edge ownership/tracer; a cycle is not a blanket veto.
    starts = [point for point, linked in neighbors.items() if len(linked) != 2]
    starts.extend(point for point, linked in neighbors.items() if len(linked) == 2)
    for start in starts:
        linked = neighbors[start]
        for following in linked:
            edge = frozenset((start, following))
            if edge in visited:
                continue
            visited.add(edge)
            path = [start, following]
            while len(neighbors[path[-1]]) == 2:
                previous, current = path[-2:]
                other = next(point for point in neighbors[current] if point != previous)
                edge = frozenset((current, other))
                if edge in visited:
                    break
                visited.add(edge)
                path.append(other)
            if len(path) >= 12:
                paths.append(np.array([(x, y) for y, x in path], dtype=float))
    # Rasterization can produce one short branch inside an otherwise continuous
    # wave. Observe each connected two-path continuation without modifying ink
    # or inventing molecular bonds. Work remains bounded by the same skeleton.
    ports: dict[tuple[float, float], list[np.ndarray]] = {}
    cyclic_windows = []
    for path in paths:
        if np.array_equal(path[0], path[-1]):
            cycle = path[:-1]
            window = min(96, len(cycle) - 1)
            for start in range(0, len(cycle), 16):
                cyclic_windows.append(cycle[(start + np.arange(window)) % len(cycle)])
                if len(cyclic_windows) > 8000:
                    raise ValueError("Source diagram exceeds the cyclic stroke budget")
            continue
        ports.setdefault(tuple(path[0]), []).append(path)
        ports.setdefault(tuple(path[-1]), []).append(path[::-1])
    joined = []
    for linked in ports.values():
        for i, left in enumerate(linked):
            for right in linked[i + 1 :]:
                joined.append(np.concatenate((left[::-1], right[1:])))
                if len(joined) > 8000:
                    raise ValueError("Source diagram exceeds the continuation budget")
    return paths + joined + cyclic_windows


def _smooth_alternating_bends(
    signal: np.ndarray, extremes: list[tuple[int, int]]
) -> bool:
    """Rounded half-waves must explain the pixels better than straight corner legs.

    Work is restricted to the already bounded, half-pixel sampled signal. A small
    blur removes raster staircases, not ink or cycles. Compare only between the
    observed extrema so connected straight bonds outside the wave cannot veto it.
    """
    from scipy.ndimage import gaussian_filter1d

    smooth = gaussian_filter1d(signal, 1.0)
    straight_error, curved_error = 0.0, 0.0
    for left, right in pairwise(extremes):
        chunk = smooth[left[0] : right[0] + 1]
        amplitude = abs(chunk[-1] - chunk[0])
        if amplitude < 0.5 or len(chunk) < 4:
            continue
        phase = np.linspace(0, 1, len(chunk))
        change = chunk[-1] - chunk[0]
        straight = chunk[0] + change * phase
        curved = chunk[0] + change * (1 - np.cos(np.pi * phase)) / 2
        straight_error += float(np.sum(abs(chunk - straight)) / amplitude)
        curved_error += float(np.sum(abs(chunk - curved)) / amplitude)
    # Low-resolution waves can have unequal rasterized plateaus. Require an
    # aggregate smooth-shape advantage, not ideal sinusoidal fit at every bend.
    return straight_error > 0 and curved_error < 0.98 * straight_error


def is_periodic_wave(points: np.ndarray) -> bool:
    """Observe repeated alternating bends, rejecting rings, labels and zigzag chains.

    A hit is only a source-symbol risk observation. It never establishes atom
    correspondence, absolute R/S, a racemate or a missing bond in the graph.
    """
    from scipy.signal import find_peaks

    centered = points - points.mean(axis=0)
    _, _, basis = np.linalg.svd(centered, full_matrices=False)
    along, across = (centered @ basis.T).T
    if along[-1] < along[0]:
        along = -along
    span = float(np.ptp(along))
    width = float(np.ptp(across))
    if not 12 <= span <= 220 or not 1.4 <= width <= 20 or not 2.5 <= span / width <= 24:
        return False
    if float(np.mean(np.diff(along) < -0.6)) > 0.1:
        return False
    order = np.argsort(along)
    x, positions = np.unique(along[order], return_index=True)
    y = across[order][positions]
    samples = np.arange(x[0], x[-1], 0.5)
    if len(samples) < 24:
        return False
    signal = np.interp(samples, x, y)
    prominence = max(0.75, width * 0.2)
    peaks = find_peaks(signal, prominence=prominence, distance=3)[0]
    troughs = find_peaks(-signal, prominence=prominence, distance=3)[0]
    extremes = sorted([(int(i), 1) for i in peaks] + [(int(i), -1) for i in troughs])
    if len(extremes) < 4 or len(extremes) > 32:
        return False
    if any(left[1] == right[1] for left, right in pairwise(extremes)):
        return False
    periods = np.diff([i for i, _ in extremes]) * 0.5
    # Skeletal carbon chains have long straight legs; wave strokes have compact
    # repeating half-periods at comparable scale to their transverse amplitude.
    return bool(
        np.std(periods) / np.mean(periods) < 0.55
        and np.mean(periods) <= width * 2.5
        and np.mean(periods) >= 1.2
        and _smooth_alternating_bends(signal, extremes)
    )
