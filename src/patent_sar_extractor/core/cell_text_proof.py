"""Pure replay of bounded complete original text rows after serialization."""

import math
import re

from patent_sar_extractor.contracts import (
    AUXILIARY_TEXT_CELL_VERSION,
    PHYSICAL_CAPTION_LINE_VERSION,
)

from .cell_ocr_scores import confidence_value
from .cell_text_chunk_proof import valid_text_chunks
from .cell_text_limits import row_pixel_limit
from .cell_text_row_readings import selected_row_reading, valid_single_row


def valid_text_reading(
    reading, bounds, dpi, *, maximum_row_height=12, maximum_rows=8, allow_chunks=False
):
    """Typed original text-cell reading, independent of its scientific role."""
    if (
        type(maximum_rows) is not int
        or not 2 <= maximum_rows <= 32
        or not isinstance(reading, dict)
    ) or (
        reading.get("method") != f"cell_ocr_{dpi}dpi"
        or type(reading.get("render_dpi")) is not int
        or reading["render_dpi"] != dpi
        or dpi not in {400, 600}
        or reading.get("bbox") != list(bounds)
        or reading.get("coordinate_space") != "original_pdf_points"
        or not isinstance(reading.get("raw_text"), str)
        or len(reading["raw_text"]) > 4096
        or reading.get("text") != reading["raw_text"]
    ):
        return False
    if "physical_text_chunks" in reading:
        return allow_chunks and valid_text_chunks(
            reading,
            dpi,
            component_validator=valid_text_components,
            maximum_row_height=maximum_row_height,
            maximum_rows=maximum_rows,
        )
    return valid_text_components(
        reading, dpi, maximum_row_height=maximum_row_height, maximum_rows=maximum_rows
    )


def valid_text_components(reading, dpi, *, maximum_row_height=12, maximum_rows=8):
    """Literal text/pixel components, with geometry owned by the calling frame."""
    if not isinstance(reading, dict):
        return False
    if _auxiliary_marker(reading, "physical_header_lines"):
        from .text_ocr.cell_proof import valid_auxiliary_cell

        return _auxiliary_limits(
            reading, 1, maximum_rows, maximum_row_height
        ) and valid_auxiliary_cell(reading, dpi)
    if (
        not isinstance(reading, dict)
        or "physical_text_chunks" in reading
        or reading.get("method") != f"cell_ocr_{dpi}dpi"
        or type(reading.get("render_dpi")) is not int
        or reading.get("render_dpi") != dpi
        or not isinstance(reading.get("raw_text"), str)
        or len(reading["raw_text"]) > 4096
        or reading.get("text") != reading["raw_text"]
    ):
        return False
    parts, detected = reading.get("parts"), reading.get("detection_parts")
    if (
        not isinstance(parts, list)
        or not 1 <= len(parts) <= 32
        or not isinstance(detected, list)
        or len(detected) > 32
        or any(
            not isinstance(part, dict)
            or not isinstance(part.get("text"), str)
            or len(part["text"]) > 4096
            or confidence_value(part.get("confidence")) is None
            or part.get("confidence_valid", True) is not True
            for part in [*parts, *detected]
        )
        or any(part["confidence"] < 0.85 for part in parts)
        or type(reading.get("confidence")) not in {int, float}
        or reading["confidence"] != min(part["confidence"] for part in parts)
    ):
        return False
    if "single_row_readings" in reading and not valid_single_row(reading, dpi):
        return False
    if "physical_header_lines" in reading:
        return physical_text_valid(
            reading,
            packet_name="physical_header_lines",
            part_method="physical_header_line",
            minimum_rows=2,
            maximum_rows=maximum_rows,
            maximum_row_height=maximum_row_height,
        )
    return " ".join(part["text"] for part in parts) == reading["raw_text"]


def physical_text_valid(
    reading,
    *,
    packet_name,
    part_method,
    minimum_rows,
    maximum_rows,
    maximum_row_height=12,
):
    """One pure bounded pixel-frame replay shared by header and caption readers."""
    if not isinstance(reading, dict):
        return False
    if _auxiliary_marker(reading, packet_name):
        from .text_ocr.cell_proof import valid_auxiliary_cell

        return (
            packet_name == "physical_header_lines"
            and part_method == "physical_header_line"
            and _auxiliary_limits(
                reading, minimum_rows, maximum_rows, maximum_row_height
            )
            and valid_auxiliary_cell(reading, reading.get("render_dpi"))
        )
    if type(maximum_row_height) is not int or not 0 < maximum_row_height <= 128:
        return False
    packet = reading.get(packet_name)
    fields = {
        "version",
        "status",
        "image_shape",
        "pixel_sha256",
        "row_bounds",
        "ink_pixels",
    }
    if not isinstance(packet, dict) or set(packet) not in (
        fields,
        fields | {"row_readings"},
    ):
        return False
    if (
        type(packet["version"]) is not int
        or packet["version"] not in {1, 2, PHYSICAL_CAPTION_LINE_VERSION}
        or packet["status"] != "observed"
        or (packet["version"] == 2) != ("row_readings" in packet)
    ):
        return False
    if packet["version"] == PHYSICAL_CAPTION_LINE_VERSION and (
        packet_name != "physical_caption_line"
        or part_method != "physical_caption_line"
        or minimum_rows != 1
        or maximum_rows != 1
        or maximum_row_height != 12
    ):
        return False
    shape, dpi, border = (
        packet["image_shape"],
        reading.get("render_dpi"),
        reading.get("border_pixels"),
    )
    crop, rows, parts = (
        reading.get("ink_crop_pixels"),
        packet["row_bounds"],
        reading.get("parts"),
    )
    if (
        not isinstance(shape, list)
        or len(shape) != 3
        or any(type(v) is not int or v <= 0 for v in shape)
        or shape[2] != 3
        or shape[0] * shape[1] > 8_000_000
        or type(dpi) is not int
        or dpi not in {400, 600}
        or type(border) is not int
        or not 0 < border <= 32
        or not isinstance(crop, list)
        or len(crop) != 4
        or any(type(v) is not int or v < 0 for v in crop)
        or shape[:2] != [crop[3] - crop[1] + 2 * border, crop[2] - crop[0] + 2 * border]
        or not isinstance(rows, list)
        or not minimum_rows <= len(rows) <= maximum_rows
        or not isinstance(parts, list)
        or len(parts) != len(rows)
        or not isinstance(packet["pixel_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", packet["pixel_sha256"])
        or type(packet["ink_pixels"]) is not int
        or not 0 < packet["ink_pixels"] <= shape[0] * shape[1]
    ):
        return False
    if packet["version"] == 2 and (
        packet_name != "physical_header_lines"
        or not isinstance(packet["row_readings"], list)
        or len(packet["row_readings"]) != len(rows)
    ):
        return False
    bottom, area, scores = border - 1, 0, []
    for index, (row, part) in enumerate(zip(rows, parts)):
        if (
            not isinstance(row, list)
            or len(row) != 4
            or any(type(v) is not int for v in row)
        ):
            return False
        x0, y0, x1, y1 = row
        if not (
            border <= x0 < x1 <= shape[1] - border
            and bottom < y0 < y1 <= shape[0] - border
            and y1 - y0 <= row_pixel_limit(dpi, maximum_row_height=maximum_row_height)
        ):
            return False
        bottom, area = y1, area + (x1 - x0) * (y1 - y0)
        if packet["version"] == 2:
            selected = selected_row_reading(
                packet["row_readings"][index], y1 - y0, border
            )
            if (
                selected is None
                or not isinstance(part, dict)
                or any(part.get(key) != selected[key] for key in ("text", "confidence"))
            ):
                return False
        if (
            not isinstance(part, dict)
            or set(part) != {"text", "confidence", "bbox", "coordinate_space", "method"}
            or not isinstance(part["text"], str)
            or not part["text"].strip()
            or len(part["text"]) > 4096
            or part["bbox"] != [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
            or part["coordinate_space"] != "cell_ink_crop_pixels"
            or part["method"] != part_method
            or type(part["confidence"]) not in {int, float}
            or not math.isfinite(part["confidence"])
            or not 0.85 <= part["confidence"] <= 1
        ):
            return False
        scores.append(part["confidence"])
    return (
        packet["ink_pixels"] <= area
        and reading.get("raw_text") == "\n".join(part["text"] for part in parts)
        and type(reading.get("confidence")) in {int, float}
        and reading["confidence"] == min(scores)
    )


def _auxiliary_marker(reading, packet_name):
    packet = reading.get(packet_name)
    return "auxiliary_text" in reading or (
        isinstance(packet, dict)
        and packet.get("version") == AUXILIARY_TEXT_CELL_VERSION
    )


def _auxiliary_limits(reading, minimum_rows, maximum_rows, maximum_row_height):
    """An auxiliary packet cannot bypass a caller's stricter physical scope."""
    parts = reading.get("parts")
    return (
        type(minimum_rows) is int
        and type(maximum_rows) is int
        and 1 <= minimum_rows <= maximum_rows <= 32
        and type(maximum_row_height) is int
        and 12 <= maximum_row_height <= 128
        and isinstance(parts, list)
        and minimum_rows <= len(parts) <= maximum_rows
    )
