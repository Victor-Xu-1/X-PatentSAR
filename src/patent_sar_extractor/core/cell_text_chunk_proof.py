"""Replay conserved original text slices; never infer or repair cell content."""

import math
import re

from .cell_text_limits import row_pixel_limit

MAX_TEXT_CHUNKS = 128
_CELL_READING_FIELDS = {
    "method",
    "text",
    "raw_text",
    "confidence",
    "parts",
    "bbox",
    "coordinate_space",
    "ink_crop_pixels",
    "border_pixels",
    "render_dpi",
    "detection_parts",
}


def text_detection_parts(reading):
    packet = reading.get("physical_text_chunks")
    if packet is None:
        return reading.get("detection_parts", [])
    chunks = packet.get("chunks") if isinstance(packet, dict) else None
    if not isinstance(chunks, list) or len(chunks) > MAX_TEXT_CHUNKS:
        return []
    parts = []
    for chunk in chunks:
        child = chunk.get("reading") if isinstance(chunk, dict) else None
        detected = child.get("detection_parts") if isinstance(child, dict) else None
        if not isinstance(detected, list) or len(detected) > 32:
            return []
        parts.extend(detected)
    return parts


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)


def _box(value, width, height):
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(type(v) is int for v in value)
        and 0 <= value[0] < value[2] <= width
        and 0 <= value[1] < value[3] <= height
    )


def valid_text_chunks(
    reading, dpi, *, component_validator, maximum_row_height, maximum_rows
):
    packet = reading.get("physical_text_chunks")
    if not isinstance(packet, dict) or set(packet) != {
        "version",
        "status",
        "image_shape",
        "pixel_sha256",
        "row_bounds",
        "ink_pixels",
        "rows_per_chunk",
        "chunks",
    }:
        return False
    shape, rows, chunks = packet["image_shape"], packet["row_bounds"], packet["chunks"]
    if (
        type(packet["version"]) is not int
        or packet["version"] != 1
        or packet["status"] != "observed"
        or not isinstance(shape, list)
        or len(shape) != 3
        or any(type(v) is not int or v <= 0 for v in shape)
        or shape[2] != 3
        or shape[0] * shape[1] > 8_000_000
        or not _sha(packet["pixel_sha256"])
        or type(packet["rows_per_chunk"]) is not int
        or packet["rows_per_chunk"] != maximum_rows
        or not isinstance(rows, list)
        or not maximum_rows < len(rows) <= maximum_rows * MAX_TEXT_CHUNKS
        or not isinstance(chunks, list)
        or not 2 <= len(chunks) <= MAX_TEXT_CHUNKS
        or len(chunks) != math.ceil(len(rows) / maximum_rows)
        or type(packet["ink_pixels"]) is not int
        or not 0 < packet["ink_pixels"] <= shape[0] * shape[1]
        or reading.get("parts") != []
        or reading.get("detection_parts") != []
        or reading.get("ink_crop_pixels") is not None
        or type(reading.get("border_pixels")) is not int
        or reading["border_pixels"] != 0
        or "physical_header_lines" in reading
    ):
        return False
    bottom = -1
    for row in rows:
        if (
            not _box(row, shape[1], shape[0])
            or row[1] <= bottom
            or row[3] - row[1]
            > row_pixel_limit(dpi, maximum_row_height=maximum_row_height)
        ):
            return False
        bottom = row[3]
    texts, scores, offset, ink = [], [], 0, 0
    for index, chunk in enumerate(chunks):
        expected = rows[index * maximum_rows : (index + 1) * maximum_rows]
        if not isinstance(chunk, dict) or set(chunk) != {
            "bbox",
            "row_bounds",
            "pixel_sha256",
            "ink_pixels",
            "reading",
        }:
            return False
        box, child = chunk["bbox"], chunk["reading"]
        if (
            not _box(box, shape[1], shape[0])
            or box[:2] != [0, offset]
            or box[2] != shape[1]
            or chunk["row_bounds"] != expected
            or not _sha(chunk["pixel_sha256"])
            or type(chunk["ink_pixels"]) is not int
            or not 0 < chunk["ink_pixels"] <= (box[3] - box[1]) * shape[1]
            or not isinstance(child, dict)
            or set(child) - {"physical_header_lines", "single_row_readings"}
            != _CELL_READING_FIELDS
            or child.get("bbox") != box
            or child.get("coordinate_space") != "cell_render_pixels"
            or not component_validator(
                child,
                dpi,
                maximum_rows=maximum_rows,
                maximum_row_height=maximum_row_height,
            )
        ):
            return False
        crop, border = child.get("ink_crop_pixels"), child.get("border_pixels")
        if (
            not _box(crop, shape[1], box[3] - box[1])
            or type(border) is not int
            or not 0 < border <= 32
        ):
            return False
        frame = child.get("physical_header_lines")
        if frame is None:
            mapped = [[crop[0], box[1] + crop[1], crop[2], box[1] + crop[3]]]
        else:
            if frame["ink_pixels"] != chunk["ink_pixels"]:
                return False
            mapped = [
                [
                    x0 - border + crop[0],
                    y0 - border + crop[1] + box[1],
                    x1 - border + crop[0],
                    y1 - border + crop[1] + box[1],
                ]
                for x0, y0, x1, y1 in frame["row_bounds"]
            ]
        if mapped != expected:
            return False
        offset = box[3]
        ink += chunk["ink_pixels"]
        texts.append(child["raw_text"])
        scores.append(child["confidence"])
    return (
        offset == shape[0]
        and ink == packet["ink_pixels"]
        and reading.get("raw_text") == reading.get("text") == "\n".join(texts)
        and type(reading.get("confidence")) in {int, float}
        and reading["confidence"] == min(scores)
    )
