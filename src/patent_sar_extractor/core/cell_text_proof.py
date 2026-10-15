"""Pure replay of bounded complete original text rows after serialization."""

import math
import re


def physical_text_valid(
    reading, *, packet_name, part_method, minimum_rows, maximum_rows
):
    """One pure bounded pixel-frame replay shared by header and caption readers."""
    packet = reading.get(packet_name)
    if not isinstance(packet, dict) or set(packet) != {
        "version",
        "status",
        "image_shape",
        "pixel_sha256",
        "row_bounds",
        "ink_pixels",
    }:
        return False
    if (
        type(packet["version"]) is not int
        or packet["version"] != 1
        or packet["status"] != "observed"
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
    bottom, area, scores = border - 1, 0, []
    for row, part in zip(rows, parts):
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
            and y1 - y0 <= 12 * dpi / 72
        ):
            return False
        bottom, area = y1, area + (x1 - x0) * (y1 - y0)
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
