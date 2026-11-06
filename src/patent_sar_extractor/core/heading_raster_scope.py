"""Original physical row ownership for raster-only heading nominations.

A locator nominates vertical text, never the final word crop. Retain a bounded
full-width context, partition every ink row, and read the complete nominated row
between its original whitespace separators. Neighboring clipped text remains
in the context proof, not in the heading's confidence or scientific identity.
"""

import math
from dataclasses import dataclass

import numpy as np

from .cell_frame_proof import inside_box
from .cell_header_lines import physical_row_bounds
from .cell_raster import cell_pixel_rect
from .cell_rule_pixels import original_rule_band
from .heading_source_geometry import MAX_HEADING_HEIGHT, heading_bounds
from .plot_reference_pixels import observe_pixels, retained_pixels
from .source_geometry import overlaps

MAX_CONTEXT_PIXELS = 8_000_000
CONTEXT_MARGIN = 16


@dataclass(frozen=True)
class RasterTitleGeometry:
    bounds: list
    refusal: str | None
    rows: tuple = ()
    selected: tuple = ()


def context_bounds(nomination, size):
    return [
        0,
        max(0, nomination[1] - CONTEXT_MARGIN),
        size[0],
        min(size[1], nomination[3] + CONTEXT_MARGIN),
    ]


def observe_raster_scope(page, nomination):
    size = [page.rect.width, page.rect.height]
    bounds = context_bounds(nomination, size)
    return {
        "version": 3,
        "method": "raster_row",
        "nomination_bbox": list(nomination),
        "page_size": size,
        "pixels": observe_pixels(page, bounds, MAX_CONTEXT_PIXELS, resolutions=(400,)),
    }


def _raster_scope_geometry(packet, nomination, size, *, foreign_windows=()):
    """Re-derive all geometry from retained pixels; no OCR/role/flag is a vote."""
    if (
        not isinstance(packet, dict)
        or set(packet)
        != {"version", "method", "nomination_bbox", "page_size", "pixels"}
        or type(packet.get("version")) is not int
        or packet["version"] != 3
        or packet["method"] != "raster_row"
        or not isinstance(nomination, (list, tuple))
        or packet["nomination_bbox"] != list(nomination)
        or packet["page_size"] != size
        or not isinstance(size, list)
        or len(size) != 2
        or any(
            type(v) not in {int, float} or not math.isfinite(v) or v <= 0 for v in size
        )
        or not inside_box(nomination, [0, 0, *size])
    ):
        return None
    bounds = context_bounds(nomination, size)
    fallback = list(heading_bounds(nomination, size))
    extent = cell_pixel_rect(bounds, 400)
    if extent.width * extent.height > MAX_CONTEXT_PIXELS:
        return (
            RasterTitleGeometry(fallback, "title_raster_pixel_budget")
            if packet["pixels"] is None
            else None
        )
    pixels = packet["pixels"]
    if (
        not isinstance(pixels, dict)
        or set(pixels) != {"bbox", "readings"}
        or pixels["bbox"] != bounds
        or not isinstance(pixels["readings"], list)
        or len(pixels["readings"]) != 1
    ):
        return None
    reading = pixels["readings"][0]
    if not isinstance(reading, dict) or "source_window" not in reading:
        return None
    window = reading["source_window"]
    if (
        "ink_mode" in reading
        or not isinstance(window, dict)
        or window.get("version") != 1
        or window.get("purpose") != "pixels"
        or window.get("frame_strips") is not None
        or window.get("read_bounds") != [0, 0, extent.width, extent.height]
    ):
        return None
    mask = retained_pixels(reading, bounds, 400, MAX_CONTEXT_PIXELS)
    if mask is None:
        return None
    if foreign_windows:
        clipped = _outside_foreign_columns(mask, extent, nomination, foreign_windows)
        if clipped is None:
            return RasterTitleGeometry(fallback, "ambiguous_original_column_title_ink")
        mask, left = clipped
        extent.x0 += left
    rows, refusal = physical_row_bounds(
        mask, 400, maximum_row_height=MAX_HEADING_HEIGHT, maximum_rows=32
    )
    if refusal is not None:
        return RasterTitleGeometry(fallback, refusal)
    original = [
        [
            (extent.x0 + row[0]) * 72 / 400,
            (extent.y0 + row[1]) * 72 / 400,
            (extent.x0 + row[2]) * 72 / 400,
            (extent.y0 + row[3]) * 72 / 400,
        ]
        for row in rows
    ]
    # A tiny overlap with the preceding line is not ownership. A short or
    # multiline locator still nominates all rows it materially intersects.
    selected = _selected_rows(original, nomination)
    if not selected or selected != list(range(selected[0], selected[-1] + 1)):
        return RasterTitleGeometry(fallback, "ambiguous_original_title_rows")
    first, last = selected[0], selected[-1]
    if rows[first][1] <= 0 or rows[last][3] >= mask.shape[0]:
        return RasterTitleGeometry(fallback, "crossing_original_title_rows")
    for row in (rows[index] for index in selected):
        for y in range(row[1], row[3]):
            # Only the current original pixel row is searched. The shared rule
            # helper's broader positional tolerance otherwise borrows a rule
            # from an adjacent physical row. Checking every row also retains a
            # rule that crosses title ink in the middle rather than at its edge.
            if original_rule_band(mask[y : y + 1], 0, 0, row[0], row[2], 400):
                return RasterTitleGeometry(fallback, "original_title_requires_cell")
    top = max(bounds[1], original[first - 1][3] if first else bounds[1])
    bottom = min(
        bounds[3], original[last + 1][1] if last + 1 < len(rows) else bounds[3]
    )
    result = [
        max(0, min(original[i][0] for i in selected) - 2),
        original[first][1] - min(1.5, (original[first][1] - top) / 2),
        min(size[0], max(original[i][2] for i in selected) + 2),
        original[last][3] + min(1.5, (bottom - original[last][3]) / 2),
    ]
    if result[3] - result[1] > MAX_HEADING_HEIGHT:
        return RasterTitleGeometry(fallback, "title_height_budget")
    return RasterTitleGeometry(result, None, tuple(original), tuple(selected))


def _outside_foreign_columns(mask, extent, nomination, windows):
    """Keep full pixels, excluding only proven foreign bands at blank seams."""
    width = mask.shape[1]
    owned = np.zeros(width, dtype=bool)
    for window in windows:
        left = max(0, math.floor(window[0] * 400 / 72) - extent.x0)
        right = min(width, math.ceil(window[2] * 400 / 72) - extent.x0)
        if left >= right or owned[left:right].any():
            return None
        owned[left:right] = True
    x0 = max(0, math.floor(nomination[0] * 400 / 72) - extent.x0)
    x1 = min(width, math.ceil(nomination[2] * 400 / 72) - extent.x0)
    if x0 >= x1 or owned[x0:x1].any():
        return None
    left, right = x0, x1
    while left and not owned[left - 1]:
        left -= 1
    while right < width and not owned[right]:
        right += 1
    # A seam with ink cannot assign that connected source to either owner.
    for seam in (left, right):
        if 0 < seam < width and mask[:, max(0, seam - 1) : min(width, seam + 1)].any():
            return None
    if np.any(mask[:, :left] & ~owned[None, :left]) or np.any(
        mask[:, right:] & ~owned[None, right:]
    ):
        return None
    return mask[:, left:right], left


def raster_column_scope_bounds(packet, nomination, size):
    from .heading_title_columns import title_column_windows

    if (
        not isinstance(packet, dict)
        or set(packet)
        != {
            "version",
            "method",
            "nomination_bbox",
            "page_size",
            "pixels",
            "column_sources",
            "original_pdf_sha256",
            "page_no",
        }
        or type(packet["version"]) is not int
        or packet["version"] != 6
        or packet["method"] != "raster_column_row"
    ):
        return None
    base = {key: packet[key] for key in ("nomination_bbox", "page_size", "pixels")}
    base.update(version=3, method="raster_row")
    try:
        windows = title_column_windows(
            packet["column_sources"],
            packet["page_no"],
            size,
            packet["original_pdf_sha256"],
            nomination,
            context_bounds(nomination, size),
        )
        if not windows:
            return None
        observed = _raster_scope_geometry(
            base, nomination, size, foreign_windows=windows
        )
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None
    return (observed.bounds, observed.refusal) if observed is not None else None


def _selected_rows(rows, nomination):
    return [
        index
        for index, row in enumerate(rows)
        if overlaps(row, nomination)
        and min(row[3], nomination[3]) - max(row[1], nomination[1])
        >= min(row[3] - row[1], nomination[3] - nomination[1]) / 2
    ]


def raster_scope_bounds(packet, nomination, size):
    observed = _raster_scope_geometry(packet, nomination, size)
    return (observed.bounds, observed.refusal) if observed is not None else None


def separate_raster_boundaries(packet, nomination):
    """Only independently owned OTHER physical rows can explain locator edges.

    This never removes a source token or certifies text. Same-row/ambiguous/
    missing owners and every native boundary retain their original refusal.
    """
    from .source_observations import source_observation_status

    if (
        not isinstance(nomination, dict)
        or nomination.get("origin") != "raster"
        or source_observation_status(
            nomination, nomination.get("bbox"), nomination.get("text")
        )
        == "invalid"
        or not isinstance(packet, dict)
    ):
        return False
    observed = _raster_scope_geometry(
        packet, packet.get("nomination_bbox"), packet.get("page_size")
    )
    if observed is None or observed.refusal is not None:
        return False
    for token in nomination.get("boundary_tokens", ()):
        owners = _selected_rows(observed.rows, token["bbox"])
        if len(owners) != 1 or owners[0] in observed.selected:
            return False
    return True


def replay_raster_scope(page, packet):
    """Read original context pixels only; never rerun a text model on replay."""
    nomination, size = packet["nomination_bbox"], packet["page_size"]
    return (
        raster_scope_bounds(packet, nomination, size) is not None
        and size == [page.rect.width, page.rect.height]
        and packet == observe_raster_scope(page, nomination)
    )
