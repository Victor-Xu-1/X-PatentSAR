"""Native binder observations and thin adapters to the shared page OCR authority."""

from __future__ import annotations

import math

from . import page_ocr_cache

try:
    import fitz

    PYMUPDF_AVAILABLE = True
except ImportError:
    fitz = None
    PYMUPDF_AVAILABLE = False


def _extract_binder_page_text(pdf_path: str, page_idx: int) -> tuple[int, str]:
    """Reopen an owned page; native text is lazy and shared OCR errors propagate."""
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_idx]
        text = page.get_text("text")
        if not text.strip():
            text = page_ocr_cache.page_text(page)
        return page_idx, text
    finally:
        doc.close()


def _extract_binder_page_lines(
    pdf_path: str, page_idx: int
) -> tuple[int, list[tuple[float, str]]]:
    doc = fitz.open(pdf_path)
    try:
        return page_idx, _get_ocr_line_coords(doc[page_idx])
    finally:
        doc.close()


def _binder_line_y(value: object) -> float:
    """Coordinate evidence cannot silently acquire an origin or nonfinite value."""
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Invalid shared binder line coordinate")
    return float(value)


def _get_ocr_line_coords(page) -> list[tuple[float, str]]:
    """Keep native PDF points or one shared OCR observation, never a private retry."""
    native = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(
                span.get("text", "") for span in line.get("spans", [])
            ).strip()
            if text:
                native.append((_binder_line_y(line["bbox"][1]), text))
    if native:
        return sorted(native, key=lambda line: line[0])

    engine = page_ocr_cache.get_ocr_engine()
    if not engine:
        return []
    lines = []
    for item in page_ocr_cache.page_ocr_lines(page, ocr_engine=engine):
        text = item.get("text")
        if not isinstance(text, str):
            raise TypeError("Invalid shared binder line text")
        if text.strip():
            lines.append((_binder_line_y(item.get("y0")), text))
    return sorted(lines, key=lambda line: line[0])
