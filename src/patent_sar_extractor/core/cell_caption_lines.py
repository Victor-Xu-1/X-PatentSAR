"""Bounded single original caption row selected before text detection."""

import hashlib

import cv2

from patent_sar_extractor.contracts import PHYSICAL_CAPTION_LINE_VERSION

from .cell_line_coverage import complete_line_bounds
from .cell_ocr_scores import confidence_score
from .cell_text_proof import physical_text_valid
from .compound_caption import prefixed_label


def observe_single_caption(image, engine, border, dpi):
    """One same-engine read only after positive complete-row pixel selection."""
    try:
        bounds = complete_line_bounds(image, [], border, dpi)
    except (ValueError, TypeError, OverflowError):
        return None  # Over-bound source stays unconfirmed, never extra inference.
    if bounds is None:
        return None
    x0, y0, x1, y1 = bounds
    packet = {
        "version": PHYSICAL_CAPTION_LINE_VERSION,
        "status": "unresolved",
        "image_shape": list(image.shape),
        "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "row_bounds": [list(bounds)],
        "ink_pixels": int((cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) < 180).sum()),
    }
    clip = cv2.copyMakeBorder(
        image[y0:y1, x0:x1],
        border,
        border,
        border,
        border,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    result, _ = engine(clip, use_det=False, use_cls=False)
    if (
        not isinstance(result, (list, tuple))
        or len(result) != 1
        or not isinstance(result[0], (list, tuple))
        or len(result[0]) != 2
        or not isinstance(result[0][0], str)
        or not 0 < len(result[0][0]) <= 4096
    ):
        return [], packet
    part = {
        "text": result[0][0],
        "confidence": confidence_score(result[0][1]),
        "bbox": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        "coordinate_space": "cell_ink_crop_pixels",
        "method": "physical_caption_line",
    }
    if part["text"].strip() and part["confidence"] >= 0.85:
        packet["status"] = "observed"
    return [part], packet


def physical_caption_valid(reading):
    """Producer and serialized binding consumers replay exactly the same proof."""
    from .text_ocr.cell_proof import has_auxiliary_text

    parts = reading.get("parts")
    auxiliary_row = isinstance(parts, (list, tuple)) and any(
        isinstance(part, dict) and part.get("method") == "physical_header_line"
        for part in parts
    )
    if (
        has_auxiliary_text(reading)
        or "physical_header_lines" in reading
        or auxiliary_row
    ):
        return has_auxiliary_text(reading) and physical_text_valid(
            reading,
            packet_name="physical_header_lines",
            part_method="physical_header_line",
            minimum_rows=1,
            maximum_rows=1,
        )
    used = isinstance(parts, (list, tuple)) and any(
        isinstance(part, dict)
        and part.get("method") in {"undetected_caption_line", "physical_caption_line"}
        for part in parts
    )
    if "physical_caption_line" not in reading and not used:
        return True  # Existing native/detected observations keep their own guards.
    packet = reading.get("physical_caption_line")
    if not isinstance(packet, dict) or type(packet.get("version")) is not int:
        return False
    method = {
        1: "undetected_caption_line",
        PHYSICAL_CAPTION_LINE_VERSION: "physical_caption_line",
    }.get(packet["version"])
    return bool(
        used
        and method is not None
        and reading.get("detection_parts") == []
        and physical_text_valid(
            reading,
            packet_name="physical_caption_line",
            part_method=method,
            minimum_rows=1,
            maximum_rows=1,
        )
        and prefixed_label(reading.get("raw_text", ""))
        and prefixed_label(reading["raw_text"]) == reading.get("text")
    )
