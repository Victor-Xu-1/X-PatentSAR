"""Original pixels distinguish padded caption hints from actual outside ink.

This proves a physical cell boundary only. It cannot qualify text, an identifier,
an annotation or a molecular assignment. All non-white original pixels count.
"""

import numpy as np

from .caption_source_windows import CAPTION_READ_PADDING
from .cell_raster import cell_pixel_rect, render_cell_raster
from .cell_rendering import CellRenderLimit
from .cell_rule_pixels import include_original_rule_joints, original_rule_band


def closed_support_bounds(cell, tokens, size):
    if not tokens:
        return None
    bounds = [
        min(cell[0], *(token["bbox"][0] for token in tokens)),
        min(cell[1], *(token["bbox"][1] for token in tokens)),
        max(cell[2], *(token["bbox"][2] for token in tokens)),
        max(cell[3], *(token["bbox"][3] for token in tokens)),
    ]
    bounds = [
        max(0, bounds[0]),
        max(0, bounds[1]),
        min(size[0], bounds[2]),
        min(size[1], bounds[3]),
    ]
    if bounds == list(cell) or any(
        abs(a - b) > CAPTION_READ_PADDING for a, b in zip(bounds, cell, strict=True)
    ):
        return None
    return bounds


def _closed_view(page, cell, bounds, dpi):
    raster = render_cell_raster(
        page, bounds, dpi, maximum_pixels=2_000_000, purpose="pixels"
    )
    extent = cell_pixel_rect(bounds, dpi)
    inner = cell_pixel_rect(cell, dpi)
    x0, y0, x1, y1 = (
        inner.x0 - extent.x0,
        inner.y0 - extent.y0,
        inner.x1 - extent.x0,
        inner.y1 - extent.y0,
    )
    height, width = raster.image.shape[:2]
    if not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height:
        return None
    ink = np.any(raster.image != 255, axis=2)
    positions = [cell[1], cell[3], cell[0], cell[2]]
    origins = [extent.y0, extent.y0, extent.x0, extent.x0]
    bands = [
        original_rule_band(ink, axis, position * dpi / 72 - origin, lo, hi, dpi)
        for axis, position, origin, lo, hi in zip(
            (0, 0, 1, 1),
            positions,
            origins,
            (x0, x0, y0, y0),
            (x1, x1, y1, y1),
            strict=True,
        )
    ]
    if any(band is None for band in bands):
        return None
    allowed = np.zeros_like(ink)
    for axis, band, position, origin in zip(
        (0, 0, 1, 1), bands, positions, origins, strict=True
    ):
        # Extending a ruler past the cell also needs the observed literal band.
        # Never fill an assumed rule through outside text or an unobserved gap.
        whole = original_rule_band(
            ink,
            axis,
            position * dpi / 72 - origin,
            0,
            width if axis == 0 else height,
            dpi,
        )
        if axis == 0:
            allowed[band, slice(None) if whole == band else slice(x0, x1)] = True
        else:
            allowed[slice(None) if whole == band else slice(y0, y1), band] = True
    include_original_rule_joints(ink, allowed, bands)
    outside = ink.copy()
    outside[y0:y1, x0:x1] = False
    if np.any(outside & ~allowed):
        return None
    return {
        "frame": raster.frame,
        "window": raster.source_window,
        "closed_bands": bands,
    }


def observe_closed_caption_scope(page, cell, tokens):
    """A bounded original support render, not another OCR/text reader."""
    bounds = closed_support_bounds(cell, tokens, (page.rect.width, page.rect.height))
    if bounds is None:
        return None
    try:
        views = [_closed_view(page, cell, bounds, dpi) for dpi in (400, 600)]
    except CellRenderLimit:
        return None  # A refused support budget never authorizes a caption carry.
    if any(view is None for view in views):
        return None
    return {"version": 1, "bounds": bounds, "views": views}


def replay_closed_caption_scope(page, cell, scope):
    """Reobserve actual pixels/rules; matching saved digests alone is not proof."""
    from .caption_cell_scope import valid_closed_caption_scope

    if not valid_closed_caption_scope(scope, list(cell)):
        raise ValueError("Malformed original closed-caption scope")
    bounds = scope["bounds"]
    if bounds[2] > page.rect.width or bounds[3] > page.rect.height:
        raise ValueError("Closed-caption support leaves its original page")
    for dpi, expected in zip((400, 600), scope["views"], strict=True):
        actual = _closed_view(page, cell, bounds, dpi)
        if actual is None or actual != expected:
            raise ValueError("Closed-caption boundary differs from original pixels")
