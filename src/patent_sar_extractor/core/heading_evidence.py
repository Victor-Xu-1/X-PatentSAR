"""Bounded original heading evidence; no activity, sequence or model guesses."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

import fitz
from PIL import Image

from .activity_identity import printed_identifier_key
from .heading_source_proof import proved_heading_declaration
from .source_geometry import native_lines, source_layout
from .source_section_roles import heading_members, section_heading

_BODY = re.compile(
    r"^(?:\[\s*\d{1,8}\s*\]|(?:Step|Stage|步骤|中间体|Intermediate)\b|"
    r"[A-Z][.)]\s|To\s+(?:a|an|the)\s|A\s+(?:solution|mixture)\b|"
    r"The\s+(?:reaction|mixture)\b)",
    re.IGNORECASE,
)


def heading_identifier(text: object) -> str:
    observation = section_heading(text)
    return (
        observation["identifier"]
        if observation and observation["role"] == "compound_heading"
        else ""
    )


def procedure_heading_boundary(text):
    """The same original procedure stop for single and plural declarations."""
    return bool(_BODY.match(str(text).strip()))


def original_heading_lines(page, cached_lines=(), source_lines=()) -> list[dict]:
    """Keep native columns separate; cached OCR lines do not invent x bounds."""
    layout = source_layout(page)
    if source_lines:
        from .binding_source_lines import source_line

        observed, coarse = [], []
        for item in source_lines:
            line = source_line(item)
            box = line.get("bbox")
            if box is None:
                coarse.append((line["y0"], line["text"]))
                continue
            if not (
                0 <= box[0] < box[2] <= page.rect.width
                and 0 <= box[1] < box[3] <= page.rect.height
            ):
                raise ValueError("Original heading line leaves the source page")
            if line.get("source") == "page_ocr":
                observed.append({**line, "y1": box[3]})
        if observed:
            if layout.native:
                raster = layout.raster_bounds
                observed.extend(
                    {**line, "y1": line["bbox"][3]}
                    for line in native_lines(layout, raster)
                )
            if coarse:
                observed.extend(original_heading_lines(page, coarse))
            return sorted(observed, key=lambda line: (line["y0"], line["bbox"][0]))
    if layout.native and layout.raster_bounds is not None:
        raster = layout.raster_bounds
        observed = [
            {
                "y0": float(y),
                "y1": float(y) + 14,
                "text": str(text),
                "bbox": [raster[0], float(y), raster[2], min(float(y) + 14, raster[3])],
                "source": "page_ocr",
            }
            for y, text in cached_lines
            if str(text).strip()
            and math.isfinite(float(y))
            and raster[1] <= float(y) < raster[3]
        ]
        for line in native_lines(layout, raster):
            observed.append({**line, "y1": line["bbox"][3]})
        return sorted(observed, key=lambda line: (line["y0"], line["bbox"][0]))
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
            bbox = list(fitz.Rect(bbox) * page.rotation_matrix)
            lines.append(
                {
                    "y0": bbox[1],
                    "y1": bbox[3],
                    "bbox": bbox,
                    "text": " ".join(w[4] for w in group),
                    "source": "native",
                    "geometry_space": "rendered",
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


def standalone_heading_evidence(
    page, block: dict, structures: list[dict], lines: list[dict], end: float
) -> tuple[dict | None, dict | None]:
    """A unique original diagram before the first procedure, never nearest wins."""
    declaration = proved_heading_declaration(block.get("heading_observation"))
    if len(heading_members(declaration)) != 1:
        return None, None
    boundaries = [
        line["y0"]
        for line in lines
        if line["y0"] > block["y0"] + 3
        and (procedure_heading_boundary(line["text"]) or section_heading(line["text"]))
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
    label = heading_members(declaration)[0]
    method = (
        "rapidocr_heading"
        if block["heading_observation"]["observations"]
        else "native_heading"
    )
    path = str(structure.get("image_path") or "")
    if label != printed_identifier_key(block["cpd"]) or not _has_drawing(path):
        return None, None
    return structure, {
        "version": 2,
        "heading_source": block["heading_observation"],
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


def _same_heading_occurrence(binding, evidence, label):
    """The ledger locator and primary structure proof name one original source.

    Both representations are retained for audit/coverage, not competing
    authorities. A valid primary cannot legitimize changed locator metadata.
    """
    block = binding.get("original_heading_evidence")
    return bool(
        isinstance(block, dict)
        and printed_identifier_key(block.get("cpd")) == label
        and type(block.get("page_no")) is int
        and block["page_no"] == evidence.get("page_no")
        and block.get("line_text") == evidence.get("heading_text")
        and block.get("bbox") == evidence.get("heading_bbox")
        and block.get("heading_observation") == evidence.get("heading_source")
    )


def valid_heading_binding_evidence(binding: dict) -> bool:
    evidence = binding.get("original_heading_structure_evidence")
    if (
        not isinstance(evidence, dict)
        or evidence.get("version") != 2
        or type(evidence.get("version")) is not int
    ):
        return False
    label = printed_identifier_key(binding.get("compound_id") or binding.get("cpd"))
    declaration = proved_heading_declaration(evidence.get("heading_source"))
    if heading_members(declaration) != [label] or not _same_heading_occurrence(
        binding, evidence, label
    ):
        return False
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
            == (
                "rapidocr_heading"
                if evidence["heading_source"]["observations"]
                else "native_heading"
            )
            and evidence["structure_id"] == binding.get("structure_id")
            and type(evidence["page_no"]) is int
            and evidence["page_no"] == binding.get("page_no")
            and evidence["candidate_count"] == 1
            and type(evidence["candidate_count"]) is int
            and re.fullmatch(r"[a-f0-9]{64}", evidence["original_pdf_sha256"])
            and evidence["original_pdf_sha256"] == binding.get("source_pdf_sha256")
            and evidence["heading_source"]["original_pdf_sha256"]
            == evidence["original_pdf_sha256"]
            and evidence["heading_source"]["page_no"] == evidence["page_no"]
            and evidence["heading_source"]["nomination"]["bbox"] == heading
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
