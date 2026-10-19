"""Known original claims cannot be replaced by a recovered observation."""

from patent_sar_extractor.core.activity_header_identity import detector_header_conflict
from patent_sar_extractor.core.cell_frame_proof import valid_cell_frame
from patent_sar_extractor.core.cell_ocr_scores import confidence_value
from patent_sar_extractor.core.cell_text_chunk_proof import (
    MAX_TEXT_CHUNKS,
    text_detection_parts,
)
from patent_sar_extractor.core.cell_text_proof import (
    valid_text_components,
    valid_text_reading,
)

from .cell_frames import literal
from .cell_packets import primary_structure


def complete_primary(reading, dpi, *, maximum_row_height=12):
    rows = (
        reading.get("text_scope", {}).get("maximum_rows", 8)
        if isinstance(reading, dict) and isinstance(reading.get("text_scope", {}), dict)
        else 8
    )
    if valid_text_components(
        reading, dpi, maximum_rows=rows, maximum_row_height=maximum_row_height
    ):
        return True
    if not isinstance(reading, dict):
        return False
    chunks, bounds = reading.get("physical_text_chunks"), reading.get("bbox")
    return bool(
        isinstance(chunks, dict)
        and isinstance(bounds, (list, tuple))
        and len(bounds) == 4
        and valid_text_reading(
            reading,
            bounds,
            dpi,
            maximum_rows=chunks.get("rows_per_chunk"),
            allow_chunks=True,
            maximum_row_height=maximum_row_height,
        )
    )


def source_metadata(primary):
    observation = {
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
        "source_frame",
        "single_row_readings",
        "physical_caption_line",
        "physical_header_lines",
        "physical_text_chunks",
        "auxiliary_text",
        "auxiliary_text_version",
        "auxiliary_text_attempts",
    }
    return {key: value for key, value in primary.items() if key not in observation}


def parts(reading):
    chunks = reading.get("physical_text_chunks")
    if chunks is None:
        return reading.get("parts", [])
    if (
        not isinstance(chunks, dict)
        or not isinstance(chunks.get("chunks"), list)
        or len(chunks["chunks"]) > MAX_TEXT_CHUNKS
    ):
        raise ValueError("Malformed original recovery text chunks")
    result = []
    for chunk in chunks["chunks"]:
        if (
            not isinstance(chunk, dict)
            or not isinstance(chunk.get("reading"), dict)
            or not isinstance(chunk["reading"].get("parts"), list)
        ):
            raise TypeError("Malformed original recovery chunk reading")
        result.extend(chunk["reading"]["parts"])
    return result


def compatible_primary(
    primary, selected, frame, dpi, maximum_rows, *, maximum_row_height=12
):
    if source_metadata(primary) != source_metadata(selected):
        return False
    bounds = selected["bbox"]
    chunks = primary.get("physical_text_chunks")
    if chunks is None:
        if not primary_structure(primary, frame, bounds, dpi):
            return False
    else:
        fresh = selected.get("physical_text_chunks")
        if (
            not isinstance(fresh, dict)
            or primary.get("bbox") != bounds
            or primary.get("coordinate_space") != "original_pdf_points"
            or primary.get("method") != f"cell_ocr_{dpi}dpi"
            or primary.get("render_dpi") != dpi
            or primary.get("crosses_boundary", False) is not False
            or primary.get("detector_conflict", False) is not False
            or "auxiliary_text" in primary
            or not valid_cell_frame(frame, primary, bounds, dpi)
            or any(
                chunks.get(key) != fresh.get(key)
                for key in (
                    "version",
                    "image_shape",
                    "pixel_sha256",
                    "row_bounds",
                    "ink_pixels",
                    "rows_per_chunk",
                )
            )
            or len(chunks.get("chunks", [])) != len(fresh["chunks"])
        ):
            return False
        for old, new in zip(chunks["chunks"], fresh["chunks"], strict=True):
            if any(
                old.get(key) != new[key]
                for key in ("bbox", "row_bounds", "pixel_sha256", "ink_pixels")
            ):
                return False
        if (
            not isinstance(primary.get("raw_text"), str)
            or primary.get("text") not in ("", primary["raw_text"])
            or primary["raw_text"]
            != "\n".join(chunk["reading"]["raw_text"] for chunk in chunks["chunks"])
        ):
            return False
    original, recovered = parts(primary), parts(selected)
    if any(
        not isinstance(part, dict)
        or not isinstance(part.get("text"), str)
        or confidence_value(part.get("confidence")) is None
        or part.get("confidence_valid", True) is not True
        for part in original
    ):
        return False
    if detector_header_conflict(text_detection_parts(primary), selected["raw_text"]):
        return False
    if len(original) == len(recovered):
        if any(
            a["confidence"] >= 0.85 and literal(a["text"]) != literal(b["text"])
            for a, b in zip(original, recovered, strict=True)
        ):
            return False
    elif any(part["confidence"] >= 0.85 for part in original):
        return False
    return valid_text_reading(
        selected,
        bounds,
        dpi,
        maximum_rows=maximum_rows,
        allow_chunks=True,
        maximum_row_height=maximum_row_height,
    )
