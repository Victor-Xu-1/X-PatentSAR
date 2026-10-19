"""Replay every captured chunk's original pixels, independently of text quality."""

import hashlib

import cv2
import numpy as np

from .cell_frame_proof import valid_ink_extent
from .cell_header_lines import physical_line_frame
from .cell_ocr_scores import confidence_value
from .cell_text_chunk_proof import _CELL_READING_FIELDS, MAX_TEXT_CHUNKS

_SOURCE_FIELDS = ("image_shape", "pixel_sha256", "row_bounds", "ink_pixels")


def _literal_reading(reading):
    return (
        isinstance(reading, dict)
        and isinstance(reading.get("raw_text"), str)
        and len(reading["raw_text"]) <= 4096
        and reading.get("text") in ("", reading["raw_text"])
        and confidence_value(reading.get("confidence")) is not None
    )


def _original_child(strip, child, box, dpi, maximum):
    if (
        not _literal_reading(child)
        or set(child) - {"physical_header_lines", "single_row_readings"}
        != _CELL_READING_FIELDS
        or child["bbox"] != box
        or child["coordinate_space"] != "cell_render_pixels"
        or child["method"] != f"cell_ocr_{dpi}dpi"
        or type(child["render_dpi"]) is not int
        or child["render_dpi"] != dpi
        or not valid_ink_extent(child, list(strip.shape))
    ):
        return False
    ys, xs = np.where(cv2.cvtColor(strip, cv2.COLOR_RGB2GRAY) < 180)
    if not len(xs):
        return False  # Each complete slice owns at least one inventoried ink row.
    crop = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    if child["ink_crop_pixels"] != crop:
        return False
    frame = child.get("physical_header_lines")
    border = child["border_pixels"]
    padded = cv2.copyMakeBorder(
        strip[crop[1] : crop[3], crop[0] : crop[2]],
        border,
        border,
        border,
        border,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    actual = physical_line_frame(padded, border, dpi, maximum_rows=maximum)
    if frame is None:
        return actual is None
    if not isinstance(frame, dict) or (
        set(frame) != {"version", "status", *_SOURCE_FIELDS, "row_readings"}
        or type(frame["version"]) is not int
        or frame["version"] != 2
        or frame["status"] not in {"observed", "unresolved"}
        or not isinstance(frame["row_readings"], list)
        or not isinstance(frame["row_bounds"], list)
        or len(frame["row_readings"]) != len(frame["row_bounds"])
    ):
        return False
    return actual is not None and all(frame[k] == actual[k] for k in _SOURCE_FIELDS)


def original_text_chunk_pixels(image, reading, dpi):
    """Unresolved observations stay unresolved, but are not pixel-tampering errors.

    Text consumers still require valid_text_reading. Every source inventory,
    including a refused row segmentation, is recomputed from the actual pixels;
    no OCR/model, inferred text, new crop, or missing-slice waiver occurs here.
    """
    packet = reading.get("physical_text_chunks")
    if (
        not _literal_reading(reading)
        or not isinstance(packet, dict)
        or (
            set(packet)
            != {"version", "status", *_SOURCE_FIELDS, "rows_per_chunk", "chunks"}
            or type(packet["version"]) is not int
            or packet["version"] != 1
            or packet["status"] not in {"observed", "unresolved"}
            or type(packet["rows_per_chunk"]) is not int
            or not 2 <= packet["rows_per_chunk"] <= 32
            or not isinstance(packet["chunks"], list)
            or len(packet["chunks"]) > MAX_TEXT_CHUNKS
            or reading.get("parts") != []
            or reading.get("detection_parts") != []
            or reading.get("ink_crop_pixels") is not None
            or type(reading.get("border_pixels")) is not int
            or reading["border_pixels"] != 0
            or "physical_header_lines" in reading
        )
    ):
        return False
    maximum = packet["rows_per_chunk"]
    actual = physical_line_frame(image, 0, dpi, maximum_rows=maximum * MAX_TEXT_CHUNKS)
    if actual is None or any(packet[k] != actual[k] for k in _SOURCE_FIELDS):
        return False
    rows, chunks = actual["row_bounds"], packet["chunks"]
    if not rows:
        return (
            packet["status"] == "unresolved"
            and chunks == []
            and reading["raw_text"] == reading["text"] == ""
            and reading["confidence"] == 0
        )
    if not maximum < len(rows) <= maximum * MAX_TEXT_CHUNKS or (
        len(chunks) != (len(rows) + maximum - 1) // maximum
    ):
        return False
    top, texts, scores, qualified = 0, [], [], True
    for start, chunk in zip(range(0, len(rows), maximum), chunks, strict=True):
        own = rows[start : start + maximum]
        end = start + len(own)
        bottom = (own[-1][3] + rows[end][1]) // 2 if end < len(rows) else image.shape[0]
        box, strip = [0, top, image.shape[1], bottom], image[top:bottom]
        if not isinstance(chunk, dict) or (
            set(chunk)
            != {"bbox", "row_bounds", "pixel_sha256", "ink_pixels", "reading"}
            or chunk["bbox"] != box
            or chunk["row_bounds"] != own
            or chunk["pixel_sha256"] != hashlib.sha256(strip.tobytes()).hexdigest()
            or type(chunk["ink_pixels"]) is not int
            or chunk["ink_pixels"]
            != int((cv2.cvtColor(strip, cv2.COLOR_RGB2GRAY) < 180).sum())
            or not _original_child(strip, chunk["reading"], box, dpi, maximum)
        ):
            return False
        child = chunk["reading"]
        texts.append(child["raw_text"])
        scores.append(child["confidence"])
        qualified = (
            qualified and bool(child["text"].strip()) and child["confidence"] >= 0.85
        )
        top = bottom
    if (
        reading["raw_text"] != "\n".join(texts)
        or reading["confidence"] != min(scores)
        or packet["status"] != ("observed" if qualified else "unresolved")
        or reading["text"] != (reading["raw_text"] if qualified else "")
    ):
        return False
    if qualified:
        from .cell_text_proof import valid_text_reading

        return valid_text_reading(
            reading, reading["bbox"], dpi, maximum_rows=maximum, allow_chunks=True
        )
    return True
