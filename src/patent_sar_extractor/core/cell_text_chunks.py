"""Long original text cells partitioned at empty pixel rows, using the sole OCR."""

import hashlib

import cv2

from .cell_header_lines import physical_line_frame
from .cell_ocr_observation import OCRObservation, observe_cell
from .cell_text_chunk_proof import MAX_TEXT_CHUNKS


def observe_text_cell(image, dpi, engine, *, rows_per_chunk=32):
    if type(rows_per_chunk) is not int or not 2 <= rows_per_chunk <= 32:
        raise ValueError("Invalid original text chunk budget")
    frame = physical_line_frame(
        image, 0, dpi, maximum_rows=rows_per_chunk * MAX_TEXT_CHUNKS
    )
    if frame is None or 0 < len(frame["row_bounds"]) <= rows_per_chunk:
        return observe_cell(
            image,
            "header",
            dpi,
            engine,
            lambda text, _kind: text,
            maximum_text_rows=rows_per_chunk,
        )
    packet = {
        **frame,
        "rows_per_chunk": rows_per_chunk,
        "chunks": [],
    }
    rows = frame["row_bounds"]
    if not rows:
        return OCRObservation(physical_text_chunks=packet)
    top = 0
    for start in range(0, len(rows), rows_per_chunk):
        own = rows[start : start + rows_per_chunk]
        end = start + len(own)
        bottom = (own[-1][3] + rows[end][1]) // 2 if end < len(rows) else image.shape[0]
        strip = image[top:bottom]
        child = observe_cell(
            strip,
            "header",
            dpi,
            engine,
            lambda text, _kind: text,
            maximum_text_rows=rows_per_chunk,
        )
        box = [0, top, image.shape[1], bottom]
        reading = child.evidence(dpi, box)
        reading["coordinate_space"] = "cell_render_pixels"
        packet["chunks"].append(
            {
                "bbox": box,
                "row_bounds": own,
                "reading": reading,
                "pixel_sha256": hashlib.sha256(strip.tobytes()).hexdigest(),
                "ink_pixels": int(
                    (cv2.cvtColor(strip, cv2.COLOR_RGB2GRAY) < 180).sum()
                ),
            }
        )
        top = bottom
    raw = "\n".join(chunk["reading"]["raw_text"] for chunk in packet["chunks"])
    confidence = min(chunk["reading"]["confidence"] for chunk in packet["chunks"])
    observed = (
        all(chunk["reading"]["text"].strip() for chunk in packet["chunks"])
        and confidence >= 0.85
    )
    packet["status"] = "observed" if observed else "unresolved"
    return OCRObservation(
        raw if observed else "", confidence, raw, physical_text_chunks=packet
    )
