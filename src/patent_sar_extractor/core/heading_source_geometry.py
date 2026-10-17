"""Pure physical bounds for original heading windows and retained pixel reads."""

import math
import re

import fitz

HEADING_PADDING = (-2, -3, 2, 5)
MAX_HEADING_HEIGHT = 128
MAX_HEADING_ROWS = 8


def heading_bounds(box, page_size):
    """Capture and replay use the same rendered-PDF rectangle arithmetic."""
    return (fitz.Rect(box) + HEADING_PADDING) & fitz.Rect(0, 0, *page_size)


def _inside(box, outer):
    return (
        isinstance(box, list)
        and len(box) == 4
        and all(type(v) in {int, float} and math.isfinite(v) for v in box)
        and outer[0] <= box[0] < box[2] <= outer[2]
        and outer[1] <= box[1] < box[3] <= outer[3]
    )


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


def _frame(frame, reading, bounds, dpi):
    if (
        not isinstance(frame, dict)
        or not isinstance(reading, dict)
        or (
            set(frame) != {"dpi", "shape", "pixel_sha256"}
            or type(frame["dpi"]) is not int
            or frame["dpi"] != dpi
            or not isinstance(frame["shape"], list)
            or len(frame["shape"]) != 3
            or any(type(v) is not int or v <= 0 for v in frame["shape"])
            or frame["shape"][2] != 3
            or frame["shape"][0] * frame["shape"][1] > 8_000_000
            or abs(frame["shape"][1] - (bounds[2] - bounds[0] - 3) * dpi / 72) > 2
            or abs(frame["shape"][0] - (bounds[3] - bounds[1] - 2.4) * dpi / 72) > 2
            or not isinstance(frame["pixel_sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", frame["pixel_sha256"])
        )
    ):
        return False
    crop, border = reading.get("ink_crop_pixels"), reading.get("border_pixels")
    if crop is None:
        return (
            reading.get("parts") == []
            and reading.get("detection_parts") == []
            and reading.get("raw_text") == reading.get("text") == ""
            and type(border) is int
            and border == 0
        )  # No ink is a valid unresolved observation, never a reading.
    if (
        type(border) is not int
        or not 0 < border <= 32
        or not _inside(crop, [0, 0, frame["shape"][1], frame["shape"][0]])
    ):
        return False
    if any(type(v) is not int for v in crop):
        return False
    pixel_bounds = [
        0,
        0,
        crop[2] - crop[0] + 2 * border,
        crop[3] - crop[1] + 2 * border,
    ]
    for name in ("parts", "detection_parts"):
        parts = reading.get(name)
        if not isinstance(parts, list) or len(parts) > 32:
            return False
        for part in parts:
            if (
                not isinstance(part, dict)
                or part.get("coordinate_space") != "cell_ink_crop_pixels"
            ):
                return False
            points = part.get("bbox")
            if points is None:
                if len(parts) != 1:
                    return False
                continue
            if (
                not isinstance(points, list)
                or len(points) != 4
                or any(
                    not isinstance(point, list)
                    or len(point) != 2
                    or any(
                        type(v) not in {int, float} or not math.isfinite(v)
                        for v in point
                    )
                    for point in points
                )
            ):
                return False
            box = [
                min(p[0] for p in points),
                min(p[1] for p in points),
                max(p[0] for p in points),
                max(p[1] for p in points),
            ]
            if not _inside(box, pixel_bounds):
                return False
    return True


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
            _frame(frame, reading, bounds, dpi)
            for frame, reading, dpi in zip(frames, readings, (400, 600))
        )
    )
