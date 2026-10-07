"""Bounded original heading evidence; no activity, sequence or model guesses."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from pathlib import Path

import fitz
from PIL import Image

from .activity_identity import PRINTED_ID, printed_identifier_key
from .page_ocr_cache import get_ocr_engine

_PARAGRAPH = r"(?:\[\s*\d{1,8}\s*\]\s*)?"
_HEADING = re.compile(
    rf"^{_PARAGRAPH}(?:(?:Synthesis|Preparation)\s+(?:of\s+)?)?"
    r"(?:Compound|Cmpd|Cpd|Example|实施例|化合物)\s*[-:.：]?\s*"
    rf"(?P<identifier>{PRINTED_ID})(?![\w/-])(?P<tail>.*)$",
    re.IGNORECASE,
)
_BODY = re.compile(
    r"^(?:\[\s*\d{1,8}\s*\]|(?:Step|Stage|步骤|中间体|Intermediate)\b|"
    r"[A-Z][.)]\s|To\s+(?:a|an|the)\s|A\s+(?:solution|mixture)\b|"
    r"The\s+(?:reaction|mixture)\b)",
    re.IGNORECASE,
)


def heading_identifier(text: object) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).strip()
    match = _HEADING.fullmatch(text)
    if not match:
        return ""
    tail = match["tail"].strip()
    # Prose/list references are not original section headings. Unknown styles
    # remain unresolved rather than expanding an arbitrary regex search.
    if tail and not (
        tail[0] in ":.：)"
        or re.match(r"^(?:Synthesis|Preparation|制备|合成)\b", tail, re.IGNORECASE)
    ):
        return ""
    if re.match(r"^[.:：)]?\s*(?:and\b|to\s+\d|through\b|及|和)", tail, re.IGNORECASE):
        return ""
    return printed_identifier_key(match["identifier"])


def original_heading_lines(page, cached_lines=()) -> list[dict]:
    """Keep native columns separate; cached OCR lines do not invent x bounds."""
    words = page.get_text("words")
    if not words:
        return [
            {
                "y0": float(y),
                "y1": float(y) + 14,
                "text": str(text),
                "bbox": [0, float(y), page.rect.width, float(y) + 14],
                "source": "page_ocr",
            }
            for y, text in cached_lines
            if str(text).strip() and math.isfinite(float(y))
        ]
    rows = {}
    for word in words:
        rows.setdefault(round(word[1] / 3), []).append(word)
    lines = []
    for _, row in sorted(rows.items()):
        groups = [[]]
        for word in sorted(row, key=lambda item: item[0]):
            if groups[-1] and word[0] - groups[-1][-1][2] > 48:
                groups.append([])
            groups[-1].append(word)
        for group in groups:
            bbox = [
                min(w[0] for w in group),
                min(w[1] for w in group),
                max(w[2] for w in group),
                max(w[3] for w in group),
            ]
            lines.append(
                {
                    "y0": bbox[1],
                    "y1": bbox[3],
                    "bbox": bbox,
                    "text": " ".join(w[4] for w in group),
                    "source": "native",
                }
            )
    return lines


def _image_digest(path: str) -> str:
    image = Path(path)
    if not image.is_file() or image.stat().st_size > 16 * 1024 * 1024:
        return ""
    with image.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _has_drawing(path: str) -> bool:
    try:
        with Image.open(path) as image:
            if not 25 <= image.width <= 4096 or not 25 <= image.height <= 4096:
                return False
            ink = image.convert("L").point(lambda value: 255 if value < 180 else 0)
            box = ink.getbbox()
            return bool(box and box[2] - box[0] >= 20 and box[3] - box[1] >= 20)
    except (OSError, ValueError):
        return False


def _read_heading(page, block: dict) -> tuple[str, str]:
    bounds = fitz.Rect(block["bbox"]) + (-2, -3, 2, 5)
    bounds &= page.rect
    if bounds.is_empty:
        return "", ""
    native = page.get_text("text", clip=bounds)
    if native.strip():
        return heading_identifier(" ".join(native.split())), "native_heading"
    engine = get_ocr_engine()
    if not engine or engine[0] not in {"rapidocr", "paddlex"}:
        return "", ""
    from io import BytesIO

    import numpy as np

    from .page_ocr_cache import _paddlex_payload_from_image

    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(250 / 72, 250 / 72), clip=bounds, alpha=False
    )
    with Image.open(BytesIO(pixmap.tobytes("png"))) as image:
        if engine[0] == "rapidocr":
            result, _ = engine[1](np.array(image.convert("RGB")))
            texts = [str(row[1]) for row in result or [] if float(row[2]) >= 0.85]
        else:
            texts, _ = _paddlex_payload_from_image(image)
    return heading_identifier(" ".join(texts)), f"{engine[0]}_heading"


def standalone_heading_evidence(
    page, block: dict, structures: list[dict], lines: list[dict], end: float
) -> tuple[dict | None, dict | None]:
    """A unique original diagram before the first procedure, never nearest wins."""
    boundaries = [
        line["y0"]
        for line in lines
        if line["y0"] > block["y0"] + 3 and _BODY.match(str(line["text"]).strip())
    ]
    end = min([end, *boundaries])
    candidates = [
        structure
        for structure in structures
        if structure["page_no"] == block["page_no"]
        and block["y1"] <= float(structure["y0"])
        and float(structure["y1"]) <= end
    ]
    if len(candidates) != 1:
        return None, None
    structure = candidates[0]
    label, method = _read_heading(page, block)
    path = str(structure.get("image_path") or "")
    if label != printed_identifier_key(block["cpd"]) or not _has_drawing(path):
        return None, None
    return structure, {
        "version": 1,
        "label": label,
        "page_no": block["page_no"],
        "heading_text": block["line_text"],
        "heading_bbox": block["bbox"],
        "heading_observation": method,
        "original_pdf_sha256": structure["source_pdf_sha256"],
        "crop_sha256": _image_digest(path),
        "structure_id": str(structure["id"]),
        "structure_bbox": [structure[key] for key in ("x0", "y0", "x1", "y1")],
        "procedure_boundary_y": end,
        "candidate_count": 1,
    }


def valid_heading_binding_evidence(binding: dict) -> bool:
    evidence = binding.get("original_heading_structure_evidence")
    if (
        not isinstance(evidence, dict)
        or evidence.get("version") != 1
        or type(evidence.get("version")) is not int
    ):
        return False
    label = printed_identifier_key(binding.get("compound_id") or binding.get("cpd"))
    try:
        heading = evidence["heading_bbox"]
        crop = evidence["structure_bbox"]
        values = [*heading, *crop, evidence["procedure_boundary_y"]]
        if (
            len(heading) != 4
            or len(crop) != 4
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or v < 0
                for v in values
            )
        ):
            return False
        return bool(
            label
            and label
            == evidence["label"]
            == heading_identifier(evidence["heading_text"])
            and evidence["heading_observation"]
            in {"native_heading", "rapidocr_heading", "paddlex_heading"}
            and evidence["structure_id"] == binding.get("structure_id")
            and type(evidence["page_no"]) is int
            and evidence["page_no"] == binding.get("page_no")
            and evidence["candidate_count"] == 1
            and type(evidence["candidate_count"]) is int
            and re.fullmatch(r"[a-f0-9]{64}", evidence["original_pdf_sha256"])
            and evidence["original_pdf_sha256"] == binding.get("source_pdf_sha256")
            and evidence["crop_sha256"]
            == _image_digest(str(binding.get("image_path") or ""))
            and re.fullmatch(r"[a-f0-9]{64}", evidence["crop_sha256"])
            and crop
            == [binding.get(f"struct_{key}") for key in ("x0", "y0", "x1", "y1")]
            and heading[0] < heading[2]
            and heading[1] < heading[3] <= crop[1]
            and crop[0] < crop[2]
            and crop[1] < crop[3] <= evidence["procedure_boundary_y"]
        )
    except (KeyError, TypeError, ValueError, OSError):
        return False
