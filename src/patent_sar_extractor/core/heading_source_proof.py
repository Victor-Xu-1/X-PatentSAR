"""Replay original heading observations and literal declarations, not OCR votes."""

import re

from patent_sar_extractor.contracts import PLOT_REFERENCE_VERSION

from .cell_text_proof import valid_text_reading
from .heading_detector_identity import declaration_identity as _identity
from .heading_detector_identity import detector_conflicts
from .heading_native_claims import heading_literal as _text
from .heading_native_claims import native_heading_agrees
from .heading_source_geometry import MAX_HEADING_HEIGHT, valid_heading_geometry
from .heading_title_geometry import title_scope_bounds
from .native_window_coverage import native_window_complete, valid_native_window
from .source_cell_pixels import cell_readings_conserve_ink, closed_cell_masks
from .source_geometry import overlaps
from .source_observations import source_observation_status
from .source_section_roles import (
    heading_members,
    section_heading,
)


def _matching_original_window(proof, prior):
    return bool(
        isinstance(prior, dict)
        and prior.get("version") == 1
        and all(
            prior.get(key) == proof.get(key)
            for key in (
                "original_pdf_sha256",
                "page_no",
                "page_size",
                "nomination",
                "raster_bounds",
            )
        )
        and heading_observation_status(prior)[0] == "unresolved"
        and prior.get("status") == "unresolved"
    )


def _known_original_agrees(prior, declaration, text):
    original = prior["native_source"]
    if source_observation_status(
        original, prior["bbox"], original["text"]
    ) == "qualified" and not native_heading_agrees(prior, text):
        return False
    known = []
    known.extend(
        reading["raw_text"]
        for reading, dpi in zip(prior["observations"], (400, 600))
        if valid_text_reading(
            reading, prior["bbox"], dpi, maximum_row_height=MAX_HEADING_HEIGHT
        )
    )
    for literal in known:
        earlier = section_heading(literal)
        if earlier is None:
            if _text(literal) != _text(text):
                return False
        elif (
            _identity(earlier) != _identity(declaration)
            or "".join(literal.split()).casefold() != "".join(text.split()).casefold()
        ):
            return False
    return True


def heading_observation_status(proof):
    """Derive status from complete bounded observations; flags grant nothing."""
    if (
        isinstance(proof, dict)
        and type(proof.get("version")) is int
        and proof["version"] in {3, 4, 5, 6, PLOT_REFERENCE_VERSION}
    ):
        from .plot_reference import plot_reference_status

        return plot_reference_status(proof)
    if not isinstance(proof, dict) or (
        set(proof)
        - (
            {
                "version",
                "original_pdf_sha256",
                "page_no",
                "page_size",
                "bbox",
                "nomination",
                "native_source",
                "native_window",
                "title_scope",
                "raster_bounds",
                "observations",
                "rendered_frames",
                "status",
            }
            | (
                {"original_heading", "cell_source"}
                if proof.get("version") == 2
                else set()
            )
        )
        or type(proof.get("version")) is not int
        or proof["version"] not in {1, 2}
        or not isinstance(proof.get("original_pdf_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", proof["original_pdf_sha256"])
        or type(proof.get("page_no")) is not int
        or not 1 <= proof["page_no"] <= 20000
    ):
        return "invalid", None
    if not valid_heading_geometry(proof):
        return "invalid", None
    if "native_window" in proof and not valid_native_window(
        proof["native_window"], proof["bbox"]
    ):
        return "invalid", None
    cell_masks = None
    if "title_scope" in proof:
        title_scope = proof["title_scope"]
        if (
            isinstance(title_scope, dict)
            and title_scope.get("version") == 2
            and (
                title_scope.get("original_pdf_sha256") != proof["original_pdf_sha256"]
                or title_scope.get("page_no") != proof["page_no"]
            )
        ):
            return "invalid", None
        scoped = title_scope_bounds(
            proof["title_scope"], proof["nomination"]["bbox"], proof["page_size"]
        )
        if scoped is None:
            return "invalid", None
        if scoped[1] is not None:
            return "unresolved", None
        if proof["title_scope"]["method"] == "closed_cell":
            cell_masks = closed_cell_masks(
                proof["title_scope"]["cell_source"]["pixels"],
                proof["bbox"],
                proof["page_size"],
            )
            if cell_masks is None:
                return "invalid", None
    if proof["version"] == 2:
        cell_masks = closed_cell_masks(
            proof["cell_source"]["pixels"], proof["bbox"], proof["page_size"]
        )
        if cell_masks is None:
            return "invalid", None
    prior = proof.get("original_heading")
    if proof["version"] == 2 and not _matching_original_window(proof, prior):
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
    if (
        native["tokens"] or native.get("boundary_tokens")
    ) and "title_scope" not in proof:
        return "invalid", None
    texts = [native["text"]]
    if readings:
        if cell_masks is not None and not cell_readings_conserve_ink(
            cell_masks, readings
        ):
            return "unresolved", None
        for reading, dpi in zip(readings, (400, 600)):
            if not valid_text_reading(
                reading, bounds, dpi, maximum_row_height=MAX_HEADING_HEIGHT
            ):
                return "unresolved", None
        texts = [reading["raw_text"] for reading in readings]
        if _text(texts[0]) != _text(texts[1]):
            return "unresolved", None
        if not native_heading_agrees(proof, texts[0]):
            return "unresolved", None
    elif (
        native_status != "qualified"
        or raster is not None
        and overlaps(raster, bounds)
        or "native_window" in proof
        and not native_window_complete(proof["native_window"], native)
    ):
        return "unresolved", None
    declaration = section_heading(texts[0])
    if declaration is None:
        return "unresolved", None
    members = heading_members(declaration)
    if len(set(members)) != len(members):
        return "unresolved", None
    if (
        hint["source"] == "native"
        and _text(hint["text"]) != _text(texts[0])
        and (
            _text(hint["text"])
            not in {
                _text(native["text"]),
                _text(proof["title_scope"]["native_seed"]["text"])
                if "title_scope" in proof
                else _text(native["text"]),
            }
            or not native_heading_agrees(proof, texts[0])
        )
    ):
        return "unresolved", None
    if prior is not None and not _known_original_agrees(prior, declaration, texts[0]):
        return "unresolved", None
    if (
        detector_conflicts(readings, declaration)
        or prior is not None
        and detector_conflicts(prior["observations"], declaration, whole_cell=texts[0])
    ):
        return "unresolved", None
    return "confirmed", declaration


def proved_heading_declaration(proof):
    status, declaration = heading_observation_status(proof)
    return (
        declaration if status == "confirmed" and proof.get("status") == status else None
    )
