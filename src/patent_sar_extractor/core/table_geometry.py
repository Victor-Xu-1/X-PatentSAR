"""Shared original-PDF grid and coordinate observation authority.

Consumers own assay/structure semantics; neither OCR text order nor a second
detector implementation may become an independent row-ownership authority.
"""

from __future__ import annotations

import logging
import os
from io import BytesIO

import fitz
import numpy as np
from PIL import Image

from .page_ocr_cache import _paddlex_payload_from_image, get_ocr_engine

logger = logging.getLogger(__name__)


def cluster_positions(values: list[float], tolerance: float = 2.0) -> list[float]:
    if not values:
        return []
    groups: list[list[float]] = []
    for value in sorted(values):
        if not groups or abs(value - groups[-1][-1]) > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [sum(group) / len(group) for group in groups]


def detect_ruled_table_regions(page, dpi: int = 300) -> list[dict]:
    """Detect line-ruled table grids on a scanned page.

    The extractor intentionally works from the table lines first, then assigns
    OCR tokens to cells. This is much safer than flattening a multi-column
    activity table into plain text and trying to regex the result back apart.
    """
    try:
        from io import BytesIO

        import cv2  # type: ignore
        import numpy as np
        from PIL import Image
    except Exception as e:
        logger.warning(f"Ruled table detection unavailable: {e}")
        return []

    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
    img = np.array(Image.open(BytesIO(pix.tobytes("png"))).convert("L"))
    bw = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY_INV)[1]
    scale = 72.0 / dpi

    h_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(35, int(img.shape[1] * 0.06)), 1)
    )
    v_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(35, int(img.shape[0] * 0.035)))
    )
    h_mask = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel)
    v_mask = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel)

    h_segments = []
    contours = cv2.findContours(h_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * scale >= 80:
            h_segments.append(
                {
                    "x0": x * scale,
                    "y": (y + h / 2.0) * scale,
                    "x1": (x + w) * scale,
                }
            )

    v_segments = []
    contours = cv2.findContours(v_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h * scale >= 25:
            v_segments.append(
                {
                    "x": (x + w / 2.0) * scale,
                    "y0": y * scale,
                    "y1": (y + h) * scale,
                }
            )

    if not h_segments or not v_segments:
        return []

    # Group horizontal rules by their x-span first. Multi-panel patent tables
    # often have left/middle/right grids at the same y positions; grouping by
    # y first makes the panels interrupt each other and drops every region.
    span_groups: list[list[dict]] = []
    for seg in sorted(h_segments, key=lambda s: (s["x0"], s["x1"], s["y"])):
        matched = None
        for group in span_groups:
            ref_x0 = sum(item["x0"] for item in group) / len(group)
            ref_x1 = sum(item["x1"] for item in group) / len(group)
            if abs(seg["x0"] - ref_x0) <= 8 and abs(seg["x1"] - ref_x1) <= 8:
                matched = group
                break
        if matched is None:
            span_groups.append([seg])
        else:
            matched.append(seg)

    regions: list[dict] = []
    for group in span_groups:
        current: list[dict] = []
        for seg in sorted(group, key=lambda s: s["y"]):
            # Structure drawings have tall rows. A gap is not a table break
            # when both outer vertical rules visibly bridge the two rows.
            bridged = bool(current) and all(
                any(
                    abs(vertical["x"] - boundary) <= 8
                    and vertical["y0"] <= current[-1]["y"] + 4
                    and vertical["y1"] >= seg["y"] - 4
                    for vertical in v_segments
                )
                for boundary in (seg["x0"], seg["x1"])
            )
            if not current or seg["y"] - current[-1]["y"] <= 45 or bridged:
                current.append(seg)
                continue
            if len(current) >= 3:
                regions.append({"h": current})
            current = [seg]
        if len(current) >= 3:
            regions.append({"h": current})

    tables: list[dict] = []
    for region in regions:
        ys = cluster_positions([seg["y"] for seg in region["h"]], tolerance=2.0)
        x0 = min(seg["x0"] for seg in region["h"])
        x1 = max(seg["x1"] for seg in region["h"])
        y0, y1 = min(ys), max(ys)
        xs = cluster_positions(
            [
                seg["x"]
                for seg in v_segments
                if seg["y0"] <= y0 + 4
                and seg["y1"] >= y1 - 4
                and x0 - 8 <= seg["x"] <= x1 + 8
            ],
            tolerance=2.0,
        )
        if len(xs) < 3 or len(ys) < 3:
            continue
        if xs[0] > x0 + 8:
            xs = [x0, *xs]
        if xs[-1] < x1 - 8:
            xs = [*xs, x1]
        tables.append(
            {
                "xs": xs,
                "ys": ys,
                "bbox": (min(xs), y0, max(xs), y1),
            }
        )
    return tables


def page_tokens(
    page, dpi: int = 200, allow_tesseract: bool | None = None
) -> list[dict]:
    """Prefer original native words; otherwise observe one coordinate OCR pass."""
    words = page.get_text("words")
    if words:
        return [
            {
                "text": w[4],
                "x": (w[0] + w[2]) / 2,
                "y": (w[1] + w[3]) / 2,
                "bbox": list(w[:4]),
                "confidence": 1.0,
            }
            for w in words
        ]
    return ocr_tokens_with_positions(page, dpi=dpi, allow_tesseract=allow_tesseract)


def ocr_tokens_with_positions(
    page, dpi: int = 150, allow_tesseract: bool | None = None
) -> list[dict]:
    """Use the shared configured engine, not an extra private model instance."""
    engine = get_ocr_engine()
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
    image = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
    scale = 72.0 / dpi
    tokens = []
    if engine and engine[0] == "rapidocr":
        result, _ = engine[1](np.array(image))
        for points, text, confidence in result or []:
            if not str(text).strip():
                continue
            xs, ys = [p[0] * scale for p in points], [p[1] * scale for p in points]
            tokens.append(
                {
                    "text": str(text).strip(),
                    "x": sum(xs) / len(xs),
                    "y": sum(ys) / len(ys),
                    "bbox": [min(xs), min(ys), max(xs), max(ys)],
                    "confidence": float(confidence),
                }
            )
        return tokens
    if engine and engine[0] == "paddlex":
        texts, boxes = _paddlex_payload_from_image(image)
        for text, box in zip(texts, boxes):
            if len(box) < 4:
                continue
            x0, y0, x1, y1 = [float(v) * scale for v in box[:4]]
            tokens.append(
                {
                    "text": text,
                    "x": (x0 + x1) / 2,
                    "y": (y0 + y1) / 2,
                    "bbox": [x0, y0, x1, y1],
                }
            )
        return tokens
    if allow_tesseract is None:
        allow_tesseract = os.environ.get(
            "PATENTSAR_ALLOW_TESSERACT_FALLBACK", ""
        ).lower() in {"1", "true", "yes", "on"}
    if not allow_tesseract:
        return tokens
    import pytesseract

    data = pytesseract.image_to_data(
        image,
        lang="chi_sim+eng",
        config="--psm 11 preserve_interword_spaces=1",
        output_type=pytesseract.Output.DICT,
    )
    for index, text in enumerate(data.get("text", [])):
        text = str(text or "").strip()
        confidence = float(data["conf"][index])
        if not text or confidence < 15:
            continue
        x0, y0, width, height = (
            float(data[key][index]) * scale
            for key in ("left", "top", "width", "height")
        )
        tokens.append(
            {
                "text": text,
                "x": x0 + width / 2,
                "y": y0 + height / 2,
                "bbox": [x0, y0, x0 + width, y0 + height],
                "confidence": confidence / 100,
            }
        )
    return tokens
