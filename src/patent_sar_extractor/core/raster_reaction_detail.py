"""Full-frame high-resolution support for every proposed pixel arrow."""

import math

import cv2
import numpy as np

from .cell_raster import cell_pixel_rect, retained_pixel_origin
from .plot_reference_pixels import observe_pixels, retained_pixels
from .raster_reaction_pixels import (
    MAX_SOURCE_PIXELS,
    observe_raster_source,
    source_vectors,
)
from .raster_reaction_shapes import component_segments
from .reaction_arrows import contained
from .reaction_raster_layout import (
    pixel_source_required,
    render_pixel_support,
    source_pixel_step,
)

DETAIL_RESOLUTIONS = (400, 600)


def _window(box, bounds):
    window = [v + (-2 if i < 2 else 2) for i, v in enumerate(box)]
    if not contained(window, bounds):
        raise ValueError("Original arrow support crosses its declaration boundary")
    return window


def _detail_cost(bounds):
    return sum(
        (extent := cell_pixel_rect(bounds, dpi)).width * extent.height
        for dpi in DETAIL_RESOLUTIONS
    )


def _distance(first, last):
    return min(
        max(math.dist(first[:2], last[:2]), math.dist(first[2:], last[2:])),
        max(math.dist(first[:2], last[2:]), math.dist(first[2:], last[:2])),
    )


def _unique_match(primary, observed, compatible):
    if len(primary) != len(observed):
        return False
    matches = [
        [j for j, actual in enumerate(observed) if compatible(expected, actual)]
        for expected in primary
    ]
    return all(len(m) == 1 for m in matches) and len({m[0] for m in matches}) == len(
        primary
    )


def _detail_vectors(reading, bounds, sources):
    dpi = reading.get("dpi") if isinstance(reading, dict) else None
    if (
        type(dpi) is not int
        or dpi not in DETAIL_RESOLUTIONS
        or reading.get("ink_mode") != "nonwhite"
        or not isinstance(reading.get("source_window"), dict)
        or reading["source_window"].get("purpose") != "pixels"
        or reading["source_window"].get("frame_strips") is not None
        or reading["source_window"].get("source_pixel_sha256")
        != reading.get("pixel_sha256")
    ):
        raise ValueError("Arrow detail is not a complete original pixel window")
    mask = retained_pixels(reading, bounds, dpi, MAX_SOURCE_PIXELS)
    if mask is None:
        raise ValueError("Invalid retained arrow detail")
    # No other ink, even a detached dot, may be removed from this complete
    # support frame to make the proposed shaft/head look unique.
    count, _ = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    if count != 2 or any(
        (mask[0].any(), mask[-1].any(), mask[:, 0].any(), mask[:, -1].any())
    ):
        raise ValueError("Original arrow detail has competing or clipped ink")
    shape = component_segments(
        mask,
        dpi / 72,
        pixel_step=source_pixel_step(sources, bounds, dpi),
        paint_support=render_pixel_support(sources, bounds, dpi),
    )
    if shape is None:
        raise ValueError("Original arrow detail does not prove its whole geometry")
    origin = retained_pixel_origin(reading, bounds, dpi)
    return {
        "segments": [
            [float(origin[i % 2] + value * 72 / dpi) for i, value in enumerate(line)]
            for line in shape["segments"]
        ],
        "filled_heads": [
            {
                "points": [
                    [
                        float(origin[i] + value * 72 / dpi)
                        for i, value in enumerate(point)
                    ]
                    for point in triangle
                ]
            }
            for triangle in shape["filled_heads"]
        ],
    }, shape["uncertainty"]


def page_vectors(packet, regions, *, original_frame=None):
    """One source adapter into the existing graph; no saved terminal authority."""
    if (
        not isinstance(packet, dict)
        or set(packet) != {"kind", "source", "details"}
        or packet["kind"] != "pixels"
    ):
        raise ValueError("Malformed original pixel-reaction page")
    vectors, windows = source_vectors(packet["source"], regions)
    if packet["source"]["frame"] != original_frame:
        raise ValueError("Pixel reaction lacks the same original enclosing frame")
    if not pixel_source_required(packet["source"]["raster_sources"], regions):
        raise ValueError("A pixel reaction cannot invent a foreign raster source")
    details = packet["details"]
    if not isinstance(details, list) or len(details) != len(windows):
        raise ValueError("Original pixel reaction lost a whole arrow support frame")
    errors, consumed = {}, 0
    for window, detail in zip(windows, details, strict=True):
        expected = _window(window["bbox"], vectors["bounds"])
        if (
            not isinstance(detail, dict)
            or set(detail) != {"bbox", "readings"}
            or detail["bbox"] != expected
        ):
            raise ValueError("Arrow support window differs from its original component")
        readings = detail["readings"]
        if not isinstance(readings, list) or len(readings) != 2:
            raise ValueError("Original arrow is missing a retained resolution")
        consumed += _detail_cost(expected)
        if consumed > MAX_SOURCE_PIXELS:
            raise ValueError("Original arrow detail aggregate pixel bound exceeded")
        primary = [vectors["segments"][index] for index in window["segments"]]
        primary_heads = [vectors["filled_heads"][index] for index in window["heads"]]
        error = window["uncertainty"]
        for dpi, reading in zip(DETAIL_RESOLUTIONS, readings, strict=True):
            if not isinstance(reading, dict) or reading.get("dpi") != dpi:
                raise ValueError("Original arrow resolution inventory changed")
            observed, radius = _detail_vectors(
                reading, expected, packet["source"]["raster_sources"]
            )
            tolerance = error + radius
            if not _unique_match(
                primary,
                observed["segments"],
                lambda a, b, tolerance=tolerance: _distance(a, b) <= tolerance,
            ):
                raise ValueError("Original arrow primitives do not correspond uniquely")
            if not _unique_match(
                primary_heads,
                observed["filled_heads"],
                lambda a, b, tolerance=tolerance: _unique_match(
                    a["points"], b["points"], lambda p, q: math.dist(p, q) <= tolerance
                ),
            ):
                raise ValueError(
                    "Original filled arrow vertices do not correspond uniquely"
                )
            error = max(error, radius)
        errors.update({index: error for index in window["segments"]})
    return vectors, errors


def observe_pixel_page(
    page, bounds, regions, *, raster_sources=None, original_frame=None
):
    source = observe_raster_source(
        page, bounds, raster_sources=raster_sources, original_frame=original_frame
    )
    _, windows = source_vectors(source, regions)
    details, consumed = [], 0
    for window in windows:
        clip = _window(window["bbox"], bounds)
        consumed += _detail_cost(clip)
        if consumed > MAX_SOURCE_PIXELS:
            raise ValueError("Original arrow detail aggregate pixel bound exceeded")
        pixels = observe_pixels(page, clip, MAX_SOURCE_PIXELS, ink_mode="nonwhite")
        if pixels is None:
            raise ValueError("Original arrow exceeds its pixel source bound")
        details.append(pixels)
    packet = {"kind": "pixels", "source": source, "details": details}
    page_vectors(packet, regions, original_frame=original_frame)
    return packet
