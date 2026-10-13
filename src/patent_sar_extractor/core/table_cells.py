"""Shared bounded cell observations for activity and structure-table readers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import fitz
import numpy as np

from .activity_identity import is_value
from .activity_values import is_explicit_missing_activity_value
from .cell_ocr_observation import OCRObservation, observe_cell
from .compound_caption import prefixed_label
from .page_ocr_cache import get_ocr_engine
from .source_geometry import native_cell_text, native_region

_ID = re.compile(r"[1-9]\d{0,3}[A-Z]?", re.IGNORECASE)


@dataclass
class CellReading:
    value: str
    bounds: tuple[float, float, float, float]
    observations: list[dict] = field(default_factory=list)
    needs_review: bool = False


def _normalize(value: str, kind: str) -> str:
    if kind == "number":
        text = str(value).strip().replace("＋", "+").replace("％", "%")
        # One shared lexical authority retains printed signs, units, missing
        # markers and uncertainty. Never join two separate numbers into one.
        return (
            text
            if is_value(text)
            and (
                is_explicit_missing_activity_value(text)
                or re.match(r"^[<>≤≥+\-]?\s*\d", text)
            )
            else ""
        )
    cleaned = re.sub(r"\s+", "", value).replace("＋", "+")
    if kind == "id":
        cleaned = cleaned.removesuffix(".")
    if kind == "label":
        return prefixed_label(cleaned)
    pattern = {
        "id": _ID,
        "letter": re.compile(r"[A-D]", re.IGNORECASE),
        "plus": re.compile(r"\+{1,3}"),
    }[kind]
    return cleaned.upper() if pattern.fullmatch(cleaned) else ""


def cell_image(page, bounds, dpi: int) -> np.ndarray:
    x0, y0, x1, y1 = bounds
    # Exclude printed grid rules, while retaining the entire cell's contents.
    clip = fitz.Rect(x0 + 1.5, y0 + 1.2, x1 - 1.5, y1 - 1.2) & page.rect
    if clip.is_empty or clip.width <= 0 or clip.height <= 0:
        raise ValueError("Invalid activity cell bounds")
    pix = page.get_pixmap(
        matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=clip, alpha=False
    )
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )[:, :, :3]


def _plus_count(image: np.ndarray, dpi: int) -> str:
    """Count printed crosses; OCR often collapses +++ into + or ++.

    Only isolated, cross-shaped, similarly sized components pass. Two binary
    thresholds must agree; arbitrary letters/noise/connected marks are refused.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    counts = []
    for threshold in (150, 200):
        binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)[1]
        n, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
        crosses = []
        for index in range(1, n):
            x, y, w, h, area = map(int, stats[index])
            if area < 8:
                continue
            if not (
                1.5 <= w * 72 / dpi <= 12
                and 1.5 <= h * 72 / dpi <= 12
                and 0.5 <= w / h <= 2
            ):
                return ""
            component = labels[y : y + h, x : x + w] == index
            row_peak, col_peak = (
                component.sum(axis=1).max(),
                component.sum(axis=0).max(),
            )
            if row_peak < 0.7 * w or col_peak < 0.7 * h or area / (w * h) > 0.7:
                return ""
            crosses.append((x, y, w, h))
        if not 1 <= len(crosses) <= 3:
            return ""
        if (
            max(c[1] + c[3] / 2 for c in crosses)
            - min(c[1] + c[3] / 2 for c in crosses)
            > dpi / 72 * 2
        ):
            return ""
        counts.append(len(crosses))
    return "+" * counts[0] if counts[0] == counts[1] else ""


def _ocr_cell(page, bounds, kind: str, dpi: int) -> OCRObservation:
    engine = get_ocr_engine()
    if not engine or engine[0] != "rapidocr":
        raise RuntimeError(
            "Cell-owned scanned biology tables require a coordinate OCR engine (RapidOCR)"
        )
    return observe_cell(cell_image(page, bounds, dpi), kind, dpi, engine[1], _normalize)


def read_cell(page, bounds, tokens: list[dict], kind: str, native: bool) -> CellReading:
    native = native_region(tokens, bounds, native)
    x0, y0, x1, y1 = bounds
    owned = [t for t in tokens if x0 + 0.5 < t["x"] < x1 - 0.5 and y0 < t["y"] < y1]
    raw = " ".join(
        t["text"] for t in sorted(owned, key=lambda t: (round(t["y"] / 3), t["x"]))
    )
    initial = _normalize(raw, kind)
    observations = [
        {"method": "native_cell" if native else "page_ocr_cell", "text": raw}
    ]
    native_raw = native_cell_text(tokens, bounds)
    native_value = _normalize(native_raw, kind) if native_raw else ""
    if not native and native_raw:
        observations.append({"method": "native_cell", "text": native_raw})
    if native:
        return CellReading(initial, bounds, observations, not bool(initial))
    if kind == "plus":
        value = _plus_count(cell_image(page, bounds, 450), 450)
        observations.append({"method": "printed_cross_components", "text": value})
        return CellReading(
            value,
            bounds,
            observations,
            not bool(value) or bool(native_value and value != native_value),
        )
    first_read = _ocr_cell(page, bounds, kind, 400)
    first = first_read.value
    observations.append(first_read.evidence(400, bounds))
    if first and first == initial and (not native_value or first == native_value):
        return CellReading(first, bounds, observations)
    second_read = _ocr_cell(page, bounds, kind, 600)
    second = second_read.value
    observations.append(second_read.evidence(600, bounds))
    agreed = bool(
        first
        and first == second
        and (not initial or first == initial)
        and (not native_value or first == native_value)
    )
    return CellReading(
        first if agreed else initial or first or second,
        bounds,
        observations,
        not agreed,
    )
