"""Replay original heading observations and literal declarations, not OCR votes."""

import re

from .cell_text_proof import valid_text_reading
from .heading_source_geometry import MAX_HEADING_HEIGHT, valid_heading_geometry
from .printed_identifiers import identifier_key, identifier_width
from .source_geometry import overlaps
from .source_observations import source_observation_status
from .source_section_roles import (
    heading_members,
    nonfinal_original_label,
    section_heading,
)


def _text(value):
    return " ".join(identifier_width(value).split()).casefold()


def _identity(declaration):
    return (
        declaration["label_kind"],
        declaration["role"],
        heading_members(declaration),
    )


def heading_observation_status(proof):
    """Derive status from complete bounded observations; flags grant nothing."""
    if (
        isinstance(proof, dict)
        and type(proof.get("version")) is int
        and proof["version"] in {3, 4}
    ):
        from .plot_reference import plot_reference_status

        return plot_reference_status(proof)
    if not isinstance(proof, dict) or (
        set(proof)
        - {
            "version",
            "original_pdf_sha256",
            "page_no",
            "page_size",
            "bbox",
            "nomination",
            "native_source",
            "raster_bounds",
            "observations",
            "rendered_frames",
            "status",
        }
        or type(proof.get("version")) is not int
        or proof["version"] != 1
        or not isinstance(proof.get("original_pdf_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", proof["original_pdf_sha256"])
        or type(proof.get("page_no")) is not int
        or not 1 <= proof["page_no"] <= 20000
    ):
        return "invalid", None
    if not valid_heading_geometry(proof):
        return "invalid", None
    bounds, hint = proof["bbox"], proof["nomination"]
    native, readings, raster = (
        proof.get("native_source"),
        proof.get("observations"),
        proof.get("raster_bounds"),
    )
    if not isinstance(native, dict) or not isinstance(readings, list):
        return "invalid", None
    native_status = source_observation_status(native, bounds, native.get("text"))
    if native.get("origin") != "native" or native_status == "invalid":
        return "invalid", None
    texts = [native["text"]]
    if readings:
        for reading, dpi in zip(readings, (400, 600)):
            if not valid_text_reading(
                reading, bounds, dpi, maximum_row_height=MAX_HEADING_HEIGHT
            ):
                return "unresolved", None
        texts = [reading["raw_text"] for reading in readings]
        if _text(texts[0]) != _text(texts[1]):
            return "unresolved", None
        if native["text"].strip() and (
            native_status != "qualified" or _text(native["text"]) != _text(texts[0])
        ):
            return "unresolved", None
    elif (
        native_status != "qualified" or raster is not None and overlaps(raster, bounds)
    ):
        return "unresolved", None
    declaration = section_heading(texts[0])
    if declaration is None:
        return "unresolved", None
    members = heading_members(declaration)
    if len(set(members)) != len(members):
        return "unresolved", None
    if hint["source"] == "native" and _text(hint["text"]) != _text(texts[0]):
        return "unresolved", None
    for reading in readings:
        for part in reading["detection_parts"]:
            if part["confidence"] < 0.85:
                continue
            observed = section_heading(part["text"])
            literal = identifier_key(part["text"], terminal_period=True)
            if (
                observed
                and _identity(observed) != _identity(declaration)
                or literal
                and literal not in heading_members(declaration)
                or not observed
                and nonfinal_original_label(part["text"])
            ):
                return "unresolved", None
    return "confirmed", declaration


def proved_heading_declaration(proof):
    status, declaration = heading_observation_status(proof)
    return (
        declaration if status == "confirmed" and proof.get("status") == status else None
    )
