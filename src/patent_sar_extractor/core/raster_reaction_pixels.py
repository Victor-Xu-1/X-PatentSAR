"""Complete bounded original pixels projected into the shared route graph."""

import cv2
import numpy as np

from .cell_raster import render_cell_raster, retained_pixel_origin
from .plot_reference_pixels import pixel_reading, retained_pixels
from .raster_reaction_shapes import component_segments
from .reaction_arrows import contained
from .reaction_pixel_frame import frame_ink
from .reaction_raster_layout import (
    observe_raster_layout,
    render_pixel_support,
    source_pixel_step,
    validate_raster_layout,
)
from .reaction_vectors import valid_rectangle, validate_vectors
from .source_geometry import overlaps

SOURCE_DPI = 200
MAX_SOURCE_PIXELS = 8_000_000
MAX_SOURCE_COMPONENTS = 20_000


def source_vectors(source, protected_regions):
    """Recompute from the whole retained mask; saved primitive claims do not vote."""
    if not isinstance(source, dict) or set(source) != {
        "version",
        "page_no",
        "page_size",
        "bounds",
        "reading",
        "raster_sources",
        "frame",
    }:
        raise ValueError("Malformed original pixel route")
    size, bounds, reading = source["page_size"], source["bounds"], source["reading"]
    if (
        type(source["version"]) is not int
        or source["version"] != 1
        or type(source["page_no"]) is not int
        or not 1 <= source["page_no"] <= 20000
        or not isinstance(size, list)
        or len(size) != 2
        or any(type(v) not in {int, float} or not 0 < v <= 100000 for v in size)
        or not valid_rectangle(bounds, size)
        or not isinstance(reading, dict)
        or reading.get("ink_mode") != "nonwhite"
        or not isinstance(reading.get("source_window"), dict)
        or reading["source_window"].get("purpose") != "pixels"
        or reading["source_window"].get("frame_strips") is not None
        or reading["source_window"].get("source_pixel_sha256")
        != reading.get("pixel_sha256")
    ):
        raise ValueError("Original pixel route lacks its complete source frame")
    mask = retained_pixels(reading, bounds, SOURCE_DPI, MAX_SOURCE_PIXELS)
    if mask is None:
        raise ValueError("Invalid retained pixel route")
    origin = retained_pixel_origin(reading, bounds, SOURCE_DPI)
    validate_raster_layout(source["raster_sources"], size, bounds)
    scale = SOURCE_DPI / 72
    ruled, rule_boxes = frame_ink(source, mask, origin, SOURCE_DPI)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    if count > MAX_SOURCE_COMPONENTS:
        raise ValueError("Original pixel route component bound exceeded")
    lines, heads, blockers, windows = [], [], [], []
    has_frame = False
    for index, (x, y, width, height, area) in enumerate(stats[1:], 1):
        box = [
            float(value)
            for value in (
                origin[0] + x / scale,
                origin[1] + y / scale,
                origin[0] + (x + width) / scale,
                origin[1] + (y + height) / scale,
            )
        ]
        local = labels[y : y + height, x : x + width] == index
        if ruled is not None and np.all(~local | ruled[y : y + height, x : x + width]):
            has_frame = True
            continue
        protected = any(contained(box, region) for region in protected_regions)
        if protected:
            blockers.append(box)
            continue
        if any(overlaps(box, region) for region in protected_regions):
            raise ValueError(
                "Original pixel component crosses an independently owned drawing"
            )
        if max(width, height) < 18 * scale:
            blockers.append(box)
            continue
        if (
            area > 100_000
            or min(x, y) <= 0
            or x + width >= mask.shape[1]
            or y + height >= mask.shape[0]
        ):
            raise ValueError("Unbounded or crossing original directional ink")
        observed = component_segments(
            local,
            scale,
            pixel_step=source_pixel_step(source["raster_sources"], box, SOURCE_DPI),
            paint_support=render_pixel_support(
                source["raster_sources"], box, SOURCE_DPI
            ),
        )
        if observed is None:
            raise ValueError("Unresolved original directional ink cannot disappear")
        start = len(lines)
        head_start = len(heads)
        lines.extend(
            [
                float(
                    round(
                        origin[axis % 2]
                        + (value + (x if axis % 2 == 0 else y)) / scale,
                        6,
                    )
                )
                for axis, value in enumerate(line)
            ]
            for line in observed["segments"]
        )
        heads.extend(
            {
                "points": [
                    [
                        float(
                            round(
                                origin[axis]
                                + (value + (x if axis == 0 else y)) / scale,
                                6,
                            )
                        )
                        for axis, value in enumerate(point)
                    ]
                    for point in triangle
                ]
            }
            for triangle in observed["filled_heads"]
        )
        windows.append(
            {
                "bbox": box,
                "segments": list(range(start, len(lines))),
                "heads": list(range(head_start, len(heads))),
                "uncertainty": observed["uncertainty"],
            }
        )
    if has_frame:
        blockers.extend(rule_boxes)
    result = {
        "version": 3,
        "page_no": source["page_no"],
        "page_size": size,
        "bounds": bounds,
        "segments": lines,
        "filled_heads": heads,
        "blockers": blockers,
    }
    validate_vectors(result)
    return result, windows


def observe_raster_source(page, bounds, *, raster_sources=None, original_frame=None):
    raster = render_cell_raster(
        page, bounds, SOURCE_DPI, maximum_pixels=MAX_SOURCE_PIXELS
    )
    return {
        "version": 1,
        "page_no": page.number + 1,
        "page_size": [page.rect.width, page.rect.height],
        "bounds": list(bounds),
        "frame": original_frame,
        "raster_sources": observe_raster_layout(page, bounds)
        if raster_sources is None
        else raster_sources,
        "reading": pixel_reading(
            raster.image,
            SOURCE_DPI,
            source_window=raster.source_window,
            ink_mode="nonwhite",
        ),
    }
