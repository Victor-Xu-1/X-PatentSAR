"""One bounded original text-row observation policy, independent of semantics."""

from .cell_ocr_scores import confidence_value

MAX_ROW_PIXELS = (128 * 600 + 71) // 72  # Existing maximum128pt at600dpi.


def row_recognition_border(height, border):
    """A compact view only removes known blank padding, never source pixels."""
    if (
        type(height) is not int
        or not 0 < height <= MAX_ROW_PIXELS
        or type(border) is not int
        or not 0 < border <= 32
    ):
        raise ValueError("Invalid original text-row recognition border")
    return max(1, min(border, max(2, round(height / 12))))


def row_observation(result, border):
    text, score = "", None
    if (
        isinstance(result, (list, tuple))
        and len(result) == 1
        and isinstance(result[0], (list, tuple))
        and len(result[0]) == 2
        and isinstance(result[0][0], str)
        and len(result[0][0]) <= 4096
    ):
        text, score = result[0][0], confidence_value(result[0][1])
    return {
        "border_pixels": border,
        "text": text,
        "confidence": score if score is not None else 0.0,
        "confidence_valid": score is not None,
    }


def qualified_row(reading):
    return bool(
        reading["text"].strip()
        and reading["confidence_valid"]
        and reading["confidence"] >= 0.85
    )


def selected_row_reading(readings, height, border):
    """Recompute the bounded policy; no highest-score voting or text joining."""
    if not isinstance(readings, list) or not 1 <= len(readings) <= 2:
        return None
    for reading in readings:
        if (
            not isinstance(reading, dict)
            or set(reading)
            != {"border_pixels", "text", "confidence", "confidence_valid"}
            or type(reading["border_pixels"]) is not int
            or not isinstance(reading["text"], str)
            or len(reading["text"]) > 4096
            or type(reading["confidence_valid"]) is not bool
            or confidence_value(reading["confidence"]) is None
            or not reading["confidence_valid"]
            and reading["confidence"] != 0
        ):
            return None
    first = readings[0]
    compact = row_recognition_border(height, border)
    if first["border_pixels"] != border:
        return None
    extra = not qualified_row(first) and compact != border
    if len(readings) != 1 + int(extra):
        return None
    if extra and readings[1]["border_pixels"] != compact:
        return None
    return readings[1] if extra and qualified_row(readings[1]) else first


def valid_single_row(reading, dpi):
    """The same exact one/two-view policy for a single short original header."""
    crop, border, rows, parts = (
        reading.get("ink_crop_pixels"),
        reading.get("border_pixels"),
        reading.get("single_row_readings"),
        reading.get("parts"),
    )
    if (
        type(dpi) is not int
        or dpi not in (400, 600)
        or not isinstance(crop, list)
        or len(crop) != 4
        or any(type(v) is not int or v < 0 for v in crop)
        or not crop[0] < crop[2]
        or not crop[1] < crop[3]
        or (crop[3] - crop[1]) * 72 / dpi > 12
        or type(border) is not int
        or border != max(3, round(dpi / 72 * 1.5))
        or reading.get("detection_parts") != []
        or not isinstance(parts, list)
        or len(parts) != 1
        or not isinstance(parts[0], dict)
        or parts[0].get("bbox") is not None
        or "physical_header_lines" in reading
        or "physical_text_chunks" in reading
        or not isinstance(rows, list)
        or len(rows) != 2
    ):
        return False
    selected = selected_row_reading(rows, crop[3] - crop[1], border)
    return bool(
        selected is not None
        and all(parts[0].get(key) == selected[key] for key in ("text", "confidence"))
        and reading.get("raw_text") == selected["text"]
    )
