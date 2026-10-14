"""Native binder observations and thin adapters to the shared page OCR authority."""

from __future__ import annotations

import math

from . import page_ocr_cache
from .source_geometry import source_layout

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
        if not text.strip() or source_layout(page).raster_bounds is not None:
            text = page_ocr_cache.page_text(page, min_native_chars=0)
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


def _get_ocr_line_observations(page) -> list[dict]:
    """Keep native PDF points or one shared OCR observation, never a private retry."""
    layout = source_layout(page)
    if layout.native and layout.raster_bounds is not None:
        _text, observations = page_ocr_cache._page_payload(page, min_native_chars=0)
        return observations
    native = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(
                span.get("text", "") for span in line.get("spans", [])
            ).strip()
            if text:
                rendered = fitz.Rect(line["bbox"]) * page.rotation_matrix
                native.append(
                    {
                        "y0": _binder_line_y(rendered.y0),
                        "text": text,
                        "bbox": list(rendered),
                        "source": "native",
                        "geometry_space": "rendered",
                    }
                )
    if native:
        return sorted(native, key=lambda line: (line["y0"], line["bbox"][0]))

    engine = page_ocr_cache.get_ocr_engine()
    if not engine:
        return []
    lines = []
    for item in page_ocr_cache.page_ocr_lines(page, ocr_engine=engine):
        text = item.get("text")
        if not isinstance(text, str):
            raise TypeError("Invalid shared binder line text")
        if text.strip():
            lines.append({**item, "y0": _binder_line_y(item.get("y0"))})
    return sorted(lines, key=lambda line: (line["y0"], line.get("bbox", [0])[0]))


def _get_ocr_line_coords(page) -> list[tuple[float, str]]:
    """Existing locator API projects the same original observer without rewriting it."""
    from .binding_source_lines import line_locators

    return line_locators(_get_ocr_line_observations(page))


def _extract_binder_source_lines(
    pdf_path: str, page_idx: int
) -> tuple[int, list[dict]]:
    doc = fitz.open(pdf_path)
    try:
        return page_idx, _get_ocr_line_observations(doc[page_idx])
    finally:
        doc.close()
