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
from .source_section_roles import (
    heading_members,
    section_heading,
)


def heading_identifier(text: object) -> str:
    observation = section_heading(text)
    return (
        observation["identifier"]
        if observation and observation["role"] == "compound_heading"
        else ""
    )


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
                "y1": min(float(y) + 14, raster[3]),
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
                "y1": min(float(y) + 14, page.rect.height),
                "text": str(text),
                "bbox": [
                    0,
                    float(y),
                    page.rect.width,
                    min(float(y) + 14, page.rect.height),
                ],
                "source": "page_ocr",
            }
            for y, text in cached_lines
            if str(text).strip()
            and math.isfinite(float(y))
            and 0 <= float(y) < page.rect.height
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


def heading_structure_evidence(
    block: dict, structures: dict[str, dict], scope: dict, *, document
) -> tuple[dict | None, dict | None]:
    """One complete original window; multiple drawings need actual reaction roles."""
    from .heading_declaration_scope import declaration_candidates
    from .heading_original_replay import validate_original_heading
    from .heading_reaction import observe_reaction_source

    declaration = proved_heading_declaration(block.get("heading_observation"))
    if (
        not declaration
        or declaration["role"] != "compound_heading"
        or len(heading_members(declaration)) != 1
        or block.get("line_text") != declaration["line_text"]
    ):
        return None, None
    candidates, complete = declaration_candidates(scope, block["heading_observation"])
    if not complete or not candidates or not all(c["inside"] for c in candidates):
        return None, None
    try:
        validate_original_heading(
            document[block["page_no"] - 1], block["heading_observation"]
        )
    except (ValueError, RuntimeError):
        return None, None
    reaction = None
    if len(candidates) == 1:
        chosen = candidates[0]["structure_id"]
    else:
        try:
            reaction = observe_reaction_source(
                document, scope, block["heading_observation"]
            )
        except (ValueError, RuntimeError):
            return None, None  # No source-role proof, not an invitation to rank.
        chosen = reaction["terminal_structure_id"]
    structure = structures.get(chosen)
    if structure is None:
        return None, None  # Another current source interpreter owns this candidate.
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
        "version": 6,
        "heading_source": block["heading_observation"],
        "label": label,
        "page_no": structure["page_no"],
        "heading_text": block["line_text"],
        "heading_bbox": block["bbox"],
        "heading_observation": method,
        "original_pdf_sha256": structure["source_pdf_sha256"],
        "crop_sha256": _image_digest(path),
        "structure_id": str(structure["id"]),
        "structure_bbox": [structure[key] for key in ("x0", "y0", "x1", "y1")],
        "declaration_scope": scope,
        "candidate_count": len(candidates),
        "reaction_source": reaction,
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
        and block["page_no"] == evidence["heading_source"]["page_no"]
        and block.get("line_text") == evidence.get("heading_text")
        and block.get("bbox") == evidence.get("heading_bbox")
        and block.get("heading_observation") == evidence.get("heading_source")
    )


def valid_heading_binding_evidence(binding: dict) -> bool:
    evidence = binding.get("original_heading_structure_evidence")
    if (
        isinstance(evidence, dict)
        and type(evidence.get("version")) is int
        and evidence["version"] == 6
    ):
        return _valid_scoped_heading(binding, evidence)
    # Old packets remain readable history, not current ownership authority.
    return False


def _valid_scoped_heading(binding, evidence):
    from .heading_declaration_scope import declaration_candidates

    if set(evidence) != {
        "version",
        "heading_source",
        "label",
        "page_no",
        "heading_text",
        "heading_bbox",
        "heading_observation",
        "original_pdf_sha256",
        "crop_sha256",
        "structure_id",
        "structure_bbox",
        "candidate_count",
        "declaration_scope",
        "reaction_source",
    }:
        return False
    try:
        label = printed_identifier_key(binding.get("compound_id") or binding.get("cpd"))
        proof = evidence["heading_source"]
        declaration = proved_heading_declaration(proof)
        if (
            not declaration
            or declaration["role"] != "compound_heading"
            or heading_members(declaration) != [label]
            or evidence["heading_text"] != declaration["line_text"]
            or any(
                printed_identifier_key(binding[name]) != label
                for name in ("cpd", "compound_id", "example_id")
                if binding.get(name)
            )
            or not _same_heading_occurrence(binding, evidence, label)
            or binding["original_heading_evidence"].get("declaration_scope")
            != evidence["declaration_scope"]
        ):
            return False
        candidates, complete = declaration_candidates(
            evidence["declaration_scope"], proof
        )
        if not complete or not candidates or not all(c["inside"] for c in candidates):
            return False
        reaction = evidence["reaction_source"]
        if reaction is None:
            if (
                len(candidates) != 1
                or binding.get("binding_rule") != "original_heading_standalone"
            ):
                return False
            candidate = candidates[0]
        else:
            from .heading_reaction import reaction_source_status

            if binding.get("binding_rule") != "original_heading_reaction_product":
                return False
            terminal = reaction_source_status(
                reaction, evidence["declaration_scope"], proof
            )
            candidate = next(c for c in candidates if c["structure_id"] == terminal)
        return bool(
            label
            and label
            == evidence["label"]
            == heading_identifier(evidence["heading_text"])
            and evidence["heading_observation"]
            == ("rapidocr_heading" if proof["observations"] else "native_heading")
            and type(evidence["candidate_count"]) is int
            and evidence["candidate_count"] == len(candidates)
            and evidence["structure_id"]
            == candidate["structure_id"]
            == binding.get("structure_id")
            and type(evidence["page_no"]) is int
            and evidence["page_no"] == candidate["page_no"] == binding.get("page_no")
            and evidence["structure_bbox"]
            == candidate["bbox"]
            == [binding.get("struct_" + k) for k in ("x0", "y0", "x1", "y1")]
            and evidence["heading_bbox"] == proof["nomination"]["bbox"]
            and evidence["original_pdf_sha256"]
            == proof["original_pdf_sha256"]
            == binding.get("source_pdf_sha256")
            and re.fullmatch(r"[a-f0-9]{64}", evidence["crop_sha256"])
            and evidence["crop_sha256"]
            == _image_digest(str(binding.get("image_path") or ""))
        )
    except (KeyError, TypeError, ValueError, OSError):
        return False
