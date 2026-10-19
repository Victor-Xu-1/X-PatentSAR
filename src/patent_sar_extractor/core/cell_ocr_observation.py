"""Bounded cell OCR observations, raw provenance and identity-only confidence."""

import re
from dataclasses import dataclass, replace

import cv2
import numpy as np

from .cell_caption_identity import refined_caption_conflicts
from .cell_caption_lines import observe_single_caption, physical_caption_valid
from .cell_header_lines import header_line_frame, observe_header_lines
from .cell_ocr_lines import resolve_overlapping_lines
from .cell_ocr_scores import confidence_score as _score
from .cell_ocr_scores import confidence_value
from .cell_text_limits import row_pixel_limit
from .cell_text_row_readings import (
    qualified_row,
    row_observation,
    row_recognition_border,
    selected_row_reading,
)
from .compound_caption import caption_identity


@dataclass(frozen=True)
class OCRObservation:
    value: str = ""
    confidence: float = 0.0
    raw_text: str = ""
    parts: tuple[dict, ...] = ()
    ink_crop_pixels: tuple[int, int, int, int] | None = None
    border_pixels: int = 0
    detection_parts: tuple[dict, ...] = ()
    physical_header_lines: dict | None = None
    physical_caption_line: dict | None = None
    physical_text_chunks: dict | None = None
    single_row_readings: list[dict] | None = None
    source_frame: dict | None = None
    text_scope: dict | None = None

    def evidence(self, dpi: int, bounds) -> dict:
        return {
            "method": f"cell_ocr_{dpi}dpi",
            "text": self.value,
            "raw_text": self.raw_text,
            "confidence": self.confidence,
            "parts": list(self.parts),
            "bbox": list(bounds),
            "coordinate_space": "original_pdf_points",
            "ink_crop_pixels": list(self.ink_crop_pixels)
            if self.ink_crop_pixels
            else None,
            "border_pixels": self.border_pixels,
            "render_dpi": dpi,
            "detection_parts": list(self.detection_parts),
            **({"text_scope": self.text_scope} if self.text_scope is not None else {}),
            **(
                {"source_frame": self.source_frame}
                if self.source_frame is not None
                else {}
            ),
            **(
                {"physical_header_lines": self.physical_header_lines}
                if self.physical_header_lines is not None
                else {}
            ),
            **(
                {"physical_caption_line": self.physical_caption_line}
                if self.physical_caption_line is not None
                else {}
            ),
            **(
                {"physical_text_chunks": self.physical_text_chunks}
                if self.physical_text_chunks is not None
                else {}
            ),
            **(
                {"single_row_readings": self.single_row_readings}
                if self.single_row_readings is not None
                else {}
            ),
        }


def _single_caption_observation(image, crop, border, dpi, engine, normalize):
    source = observe_single_caption(image, engine, border, dpi)
    if source is None:
        return None
    parts, physical = source
    raw = " ".join(part["text"] for part in parts)
    score = min((part["confidence"] for part in parts), default=0.0)
    observation = OCRObservation(
        normalize(raw, "label") if score >= 0.85 else "",
        score,
        raw,
        tuple(parts),
        crop,
        border,
        physical_caption_line=physical,
    )
    if not physical_caption_valid(observation.evidence(dpi, ())):
        return replace(observation, value="")
    return observation


def observe_cell(
    image: np.ndarray,
    kind: str,
    dpi: int,
    engine,
    normalize,
    *,
    maximum_text_rows=8,
    maximum_row_height=None,
) -> OCRObservation:
    """Use the existing coordinate OCR engine, never a second inference chain.

    Captions first select a complete short original ink row, then use the same
    engine without fragment detection. Other layouts retain bounded detection;
    scalar cells keep direct recognition. All observations remain source-bound.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    ink_y, ink_x = np.where(gray < 180)
    if not len(ink_x):
        return OCRObservation()
    crop = (
        int(ink_x.min()),
        int(ink_y.min()),
        int(ink_x.max()) + 1,
        int(ink_y.max()) + 1,
    )
    image = image[crop[1] : crop[3], crop[0] : crop[2]]
    border = max(3, round(dpi / 72 * 1.5))
    image = cv2.copyMakeBorder(
        image,
        border,
        border,
        border,
        border,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    if kind == "label":
        caption = _single_caption_observation(
            image, crop, border, dpi, engine, normalize
        )
        if caption is not None:
            return caption
    # A bounded one-line header cell can be a single printed "n" or "%";
    # line detection routinely suppresses those legitimate tiny observations.
    # Multiline headers/captions and unproved physical rows retain detection.
    text_region = kind in {"header", "heading"}
    row_height = (
        (128 if kind == "heading" else 12)
        if maximum_row_height is None
        else maximum_row_height
    )
    header_frame = (
        header_line_frame(
            image,
            border,
            dpi,
            maximum_row_height=row_height,
            maximum_rows=maximum_text_rows,
        )
        if text_region
        else None
    )
    detected = kind == "label" or (
        text_region
        and (
            header_frame is not None
            or crop[3] - crop[1] > row_pixel_limit(dpi, maximum_row_height=row_height)
        )
    )
    result, _ = engine(image, use_det=detected, use_cls=False)
    # The same bounded row parser owns short headers before any positional
    # indexing. A malformed response is an invalid observation, not a crash or
    # permission to coerce a dictionary/scalar into apparently recognized text.
    first = (
        row_observation(result, border) if kind == "header" and not detected else None
    )
    components = [[first["text"], first["confidence"]]] if first is not None else result
    parts = []
    for item in components or []:
        raw_confidence = item[2] if detected else item[1]
        parts.append(
            {
                "text": str(item[1] if detected else item[0]),
                "confidence": _score(raw_confidence),
                **(
                    {"confidence_valid": False}
                    if confidence_value(raw_confidence) is None
                    else {}
                ),
                "bbox": [[float(x), float(y)] for x, y in item[0]]
                if detected
                else None,
                "coordinate_space": "cell_ink_crop_pixels",
            }
        )
    detection_parts = tuple(parts) if detected else ()
    single_readings = None
    if first is not None:
        compact = row_recognition_border(crop[3] - crop[1], border)
        if not qualified_row(first) and compact != border:
            view = cv2.copyMakeBorder(
                image[border:-border, border:-border],
                compact,
                compact,
                compact,
                compact,
                cv2.BORDER_CONSTANT,
                value=(255, 255, 255),
            )
            extra, _ = engine(view, use_det=False, use_cls=False)
            single_readings = [first, row_observation(extra, compact)]
            selected = selected_row_reading(single_readings, crop[3] - crop[1], border)
            parts = [
                {
                    "text": selected["text"],
                    "confidence": selected["confidence"],
                    "bbox": None,
                    "coordinate_space": "cell_ink_crop_pixels",
                }
            ]
    header_lines = (
        observe_header_lines(image, engine, border, dpi, frame=header_frame)
        if header_frame is not None
        else None
    )
    resolved = (
        resolve_overlapping_lines(
            image, parts, engine, border, complete_lines=kind == "label", dpi=dpi
        )
        if detected and header_frame is None
        else parts
    )
    if resolved is not None:
        parts = resolved
    if header_lines is not None:
        parts, physical = header_lines
        resolved = parts if physical["status"] == "observed" else None
    if detected:
        parts.sort(
            key=lambda item: (
                round(min(p[1] for p in item["bbox"]) * 72 / dpi / 3),
                min(p[0] for p in item["bbox"]),
            )
        )
    raw = ("\n" if header_lines is not None else " ").join(
        part["text"] for part in parts
    )
    value = (
        normalize(raw, kind)
        if resolved is not None and (detected or len(parts) == 1)
        else ""
    )
    if (
        kind == "label"
        and value
        and refined_caption_conflicts(value, parts, detection_parts)
    ):
        value = ""
    score = min((part["confidence"] for part in parts), default=0.0)
    if kind == "label" and value:
        _, identity_end = caption_identity(raw)
        # Only a completely recognized literal annotation may be separated.
        # Every fragment touching the ID/prefix must pass its own confidence.
        offset, identity_scores = 0, []
        for part in parts:
            length = len(re.sub(r"\s+", "", part["text"]))
            if offset < identity_end and length:
                identity_scores.append(part["confidence"])
            offset += length
        score = min(identity_scores, default=0.0)
    observation = OCRObservation(
        value if score >= 0.85 else "",
        score,
        raw,
        tuple(parts),
        crop,
        border,
        detection_parts,
        header_lines[1] if header_lines is not None else None,
        None,
        single_row_readings=single_readings,
    )
    return observation
