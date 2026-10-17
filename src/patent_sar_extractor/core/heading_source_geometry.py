"""Pure physical bounds for original heading windows and retained pixel reads."""

import math

import fitz

from .cell_frame_proof import inside_box as _inside
from .cell_frame_proof import valid_cell_frame

HEADING_PADDING = (-2, -3, 2, 5)
MAX_HEADING_HEIGHT = 128
MAX_HEADING_ROWS = 8


def heading_bounds(box, page_size):
    """Capture and replay use the same rendered-PDF rectangle arithmetic."""
    return (fitz.Rect(box) + HEADING_PADDING) & fitz.Rect(0, 0, *page_size)


def _nomination(hint, bounds):
    if not isinstance(hint, dict) or (
        set(hint) - {"text", "source", "geometry_space", "bbox", "rows"}
        or not isinstance(hint.get("text"), str)
        or len(hint["text"]) > 4096
        or hint.get("source") not in {"native", "page_ocr"}
        or hint.get("geometry_space") not in {"rendered", "locator"}
        or not _inside(hint.get("bbox"), bounds)
    ):
        return False
    if "rows" not in hint:
        return True
    rows = hint["rows"]
    if not isinstance(rows, list) or not 2 <= len(rows) <= MAX_HEADING_ROWS:
        return False
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or (
            set(row) != {"text", "bbox", "source"}
            or not isinstance(row["text"], str)
            or len(row["text"]) > 4096
            or row["source"] != hint["source"]
            or not _inside(row["bbox"], hint["bbox"])
        ):
            return False
        if index:
            prior, current = rows[index - 1]["bbox"], row["bbox"]
            height = max(prior[3] - prior[1], current[3] - current[1])
            if not (
                current[1] > prior[1]
                and -2 <= current[1] - prior[3] <= height / 2
                and rows[0]["bbox"][0] - 2 <= current[0] <= rows[0]["bbox"][2]
            ):
                return False
    return hint["text"] == "\n".join(row["text"] for row in rows) and hint["bbox"] == [
        min(row["bbox"][0] for row in rows),
        min(row["bbox"][1] for row in rows),
        max(row["bbox"][2] for row in rows),
        max(row["bbox"][3] for row in rows),
    ]


def valid_heading_geometry(proof):
    size, bounds = proof.get("page_size"), proof.get("bbox")
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(type(v) not in {int, float} or not math.isfinite(v) for v in size)
    ):
        return False
    if not _inside(bounds, [0, 0, *size]) or bounds[3] - bounds[1] > MAX_HEADING_HEIGHT:
        return False
    hint, raster = proof.get("nomination"), proof.get("raster_bounds")
    if not _nomination(hint, bounds):
        return False
    if bounds != list(heading_bounds(hint["bbox"], size)):
        return False
    if raster is not None and not _inside(raster, [0, 0, *size]):
        return False
    readings, frames = proof.get("observations"), proof.get("rendered_frames")
    return (
        isinstance(readings, list)
        and len(readings) in {0, 2}
        and isinstance(frames, list)
        and len(frames) == len(readings)
        and all(
            valid_cell_frame(frame, reading, bounds, dpi)
            for frame, reading, dpi in zip(frames, readings, (400, 600))
        )
    )
