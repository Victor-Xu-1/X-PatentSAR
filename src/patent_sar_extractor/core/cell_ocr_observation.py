"""Bounded cell OCR observations, raw provenance and identity-only confidence."""

import re
from dataclasses import dataclass, replace

import cv2
import numpy as np

from .cell_caption_identity import refined_caption_conflicts
from .cell_caption_lines import observe_undetected_caption, physical_caption_valid
from .cell_header_lines import header_line_frame, observe_header_lines
from .cell_ocr_lines import resolve_overlapping_lines
from .cell_ocr_scores import confidence_score as _score
from .cell_ocr_scores import confidence_value
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
        }


def observe_cell(
    image: np.ndarray, kind: str, dpi: int, engine, normalize
) -> OCRObservation:
    """Use the existing coordinate OCR engine, never a second inference chain.

    Labels start with line detection, including short one-line captions. Scalar
    cells retain direct recognition. Every returned reading includes original
    text, line confidence and crop coordinates even when normalization fails.
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
    # A bounded one-line header cell can be a single printed "n" or "%";
    # line detection routinely suppresses those legitimate tiny observations.
    # Multiline headers and every compound caption still use line detection.
    header_frame = header_line_frame(image, border, dpi) if kind == "header" else None
    detected = kind == "label" or (
        kind == "header"
        and (header_frame is not None or (crop[3] - crop[1]) * 72 / dpi > 12)
    )
    result, _ = engine(image, use_det=detected, use_cls=False)
    parts = []
    for item in result or []:
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
    caption_line = (
        observe_undetected_caption(image, engine, border, dpi)
        if kind == "label" and not detection_parts
        else None
    )
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
    if caption_line is not None:
        parts, physical = caption_line
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
        caption_line[1] if caption_line is not None else None,
    )
    # This replay owns the pixel frame only. The caller supplies and verifies
    # actual original-PDF cell bounds; no point geometry is invented here.
    if caption_line is not None and not physical_caption_valid(
        observation.evidence(dpi, ())
    ):
        return replace(observation, value="")
    return observation
