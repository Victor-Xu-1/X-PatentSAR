"""Complete original graphic/text rows, using the shared physical-row SDK."""

import numpy as np

from .cell_frame_proof import inside_box
from .cell_header_lines import physical_line_frame
from .cell_raster import retained_pixel_origin
from .plot_reference_geometry import literal_bounds
from .plot_reference_marker import marker_extent
from .plot_reference_pixels import retained_pixels
from .source_geometry import overlaps

MAX_LOCATOR_PIXELS = 250_000
MAX_LEGEND_ROWS = 8


def locator_bounds(line, size):
    box = line["bbox"]
    return [
        max(0, box[0] - 26),
        max(0, box[1] - 2),
        min(size[0], box[2] + 2),
        min(size[1], box[3] + 2),
    ]


def _point_box(box, bounds, dpi, reading):
    origin = retained_pixel_origin(reading, bounds, dpi)
    return [v * 72 / dpi + origin[i % 2] for i, v in enumerate(box)]


def _separate(mask, bounds, dpi, height, reading, *, row_top=0):
    columns = np.flatnonzero(mask.any(axis=0))
    if not len(columns):
        return None
    groups = np.split(columns, np.flatnonzero(np.diff(columns) > 1) + 1)
    if not 2 <= len(groups) <= 128:
        return None
    left, right = int(groups[0][0]), int(groups[0][-1]) + 1
    rows = np.flatnonzero(mask[:, left:right].any(axis=1))
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    text_left, text_right = int(groups[1][0]), int(groups[-1][-1]) + 1
    text_rows = np.flatnonzero(mask[:, text_left:text_right].any(axis=1))
    if height is None:
        # The original literal cell has two shared insets: the nominated text
        # frame and its reading window. Use that complete TEXT window's height,
        # not a glyph-only height or a height inflated by the proposed key.
        height = (int(text_rows[-1]) - int(text_rows[0]) + 1) * 72 / dpi + 4.8
    if marker_extent(mask[top:bottom, left:right], dpi, height) is None:
        return None
    # Every non-key pixel belongs to this complete row; no word chooses a cut.
    return {
        "key": _point_box(
            [left, top + row_top, right, bottom + row_top], bounds, dpi, reading
        ),
        "text": _point_box(
            [
                text_left,
                int(text_rows[0]) + row_top,
                text_right,
                int(text_rows[-1]) + 1 + row_top,
            ],
            bounds,
            dpi,
            reading,
        ),
    }


def locator_rows(pixels, line, size, *, multiline):
    """Replay all retained ink, not a successful row subset or detector vote."""
    bounds = locator_bounds(line, size)
    if (
        not isinstance(pixels, dict)
        or set(pixels) != {"bbox", "readings"}
        or pixels["bbox"] != bounds
        or not isinstance(pixels["readings"], list)
        or len(pixels["readings"]) != 2
    ):
        return None
    results = []
    for reading, dpi in zip(pixels["readings"], (400, 600)):
        mask = retained_pixels(reading, bounds, dpi, MAX_LOCATOR_PIXELS)
        if mask is None:
            return None
        # Binary projection nominates geometry only. Original RGB digests and
        # full-window masks remain the retained source, without ink edits.
        frame = (
            physical_line_frame(
                np.repeat(
                    np.where(mask[..., None], 0, 255).astype(np.uint8), 3, axis=2
                ),
                0,
                dpi,
                maximum_row_height=32,
                maximum_rows=MAX_LEGEND_ROWS,
            )
            if multiline
            else None
        )
        row_bounds = (
            frame["row_bounds"]
            if frame is not None
            else [[0, 0, mask.shape[1], mask.shape[0]]]
        )
        if not row_bounds:
            return None  # An over-bound inventory cannot fall back to one row.
        parts = []
        for _, top, _, bottom in row_bounds:
            split = _separate(
                mask[top:bottom],
                bounds,
                dpi,
                None if multiline else line["bbox"][3] - line["bbox"][1],
                reading,
                row_top=top,
            )
            if split is None:
                return None
            parts.append(split)
        results.append(parts)
    if len(results[0]) != len(results[1]):
        return None
    combined = []
    for first, second in zip(*results):
        if any(
            abs(a - b) > 1.2
            for name in ("key", "text")
            for a, b in zip(first[name], second[name])
        ):
            return None
        merged = {
            name: [
                min(first[name][0], second[name][0]),
                min(first[name][1], second[name][1]),
                max(first[name][2], second[name][2]),
                max(first[name][3], second[name][3]),
            ]
            for name in ("key", "text")
        }
        text = literal_bounds(merged["text"], size)
        if not inside_box(text, bounds) or not overlaps(text, line["bbox"]):
            return None
        combined.append({"bbox": text, "key": merged["key"]})
    return combined
