"""Shared bounded cell observations for activity and structure-table readers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

import numpy as np

from .activity_identity import is_value
from .activity_values import is_explicit_missing_activity_value
from .cell_cross_observation import observe_printed_crosses
from .cell_ocr_observation import OCRObservation, observe_cell
from .cell_raster import render_cell_raster
from .cell_rendering import CellRenderLimit
from .compound_caption import prefixed_label
from .page_ocr_cache import get_ocr_engine
from .printed_identifiers import identifier_key
from .source_cell_claims import cell_source_conflict, cell_source_status
from .source_cell_tokens import cell_text
from .source_geometry import SourceTokens, native_cell_text, native_region
from .source_observations import source_cell_observation
from .source_section_roles import nonfinal_original_label

__all__ = [
    "CellReading",
    "CellRenderLimit",
    "activity_kind_matches",
    "cell_image",
    "observe_original_cell",
    "read_cell",
]


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
    if kind == "id":
        return identifier_key(value, wrapped=True, terminal_period=True)
    if kind == "label":
        return prefixed_label(value)
    cleaned = re.sub(r"\s+", "", value).replace("＋", "+")
    pattern = {
        "letter": re.compile(r"[A-G](?:[12])?", re.IGNORECASE),
        "plus": re.compile(r"\+{1,3}"),
    }[kind]
    return cleaned.upper() if pattern.fullmatch(cleaned) else ""


def activity_kind_matches(value: str, kind: str) -> bool:
    """Original literal categories, not quantitative grade thresholds/direction."""
    if not isinstance(value, str):
        return False
    if is_explicit_missing_activity_value(value):
        return True
    if kind == "plus":
        return bool(re.fullmatch(r"\+{1,5}", str(value).strip()))
    return kind in {"number", "letter"} and bool(_normalize(value, kind))


def cell_image(
    page, bounds, dpi: int, *, maximum_pixels: int = 8_000_000
) -> np.ndarray:
    return render_cell_raster(
        page, bounds, dpi, maximum_pixels=maximum_pixels, purpose="pixels"
    ).image


def _ocr_cell(page, bounds, kind: str, dpi: int) -> OCRObservation:
    engine = get_ocr_engine()
    if not engine or engine[0] != "rapidocr":
        raise RuntimeError(
            "Cell-owned scanned biology tables require a coordinate OCR engine (RapidOCR)"
        )
    return observe_original_cell(page, bounds, kind, dpi, engine[1], _normalize)


def observe_original_cell(page, bounds, kind, dpi, engine, normalize) -> OCRObservation:
    """One original rendering/observation envelope for scalar and text readers."""
    raster = render_cell_raster(page, bounds, dpi, purpose="text")
    observed = observe_cell(raster.image, kind, dpi, engine, normalize)
    return replace(
        observed,
        source_frame=raster.frame,
        source_window=raster.source_window,
    )


def read_cell(page, bounds, tokens: list[dict], kind: str, native: bool) -> CellReading:
    native = native_region(tokens, bounds, native)
    raw = cell_text(tokens, bounds)
    initial = _normalize(raw, kind)
    original = {
        "method": "native_cell" if native else "page_ocr_cell",
        "text": raw,
        "bbox": list(bounds),
    }
    profile = source_cell_observation(tokens, bounds, native=native)
    if profile is not None:
        original.update(source_observation=profile)
    observations = [original]
    native_raw = native_cell_text(tokens, bounds)
    native_value = _normalize(native_raw, kind) if native_raw else ""
    nonfinal = kind in {"id", "label"} and nonfinal_original_label(
        native_raw if not native else raw
    )
    if not native and native_raw:
        shadow = {
            "method": "native_cell",
            "native_role": "witness",
            "text": native_raw,
            "bbox": list(bounds),
        }
        native_profile = source_cell_observation(tokens, bounds, native=True)
        if native_profile is not None:
            shadow.update(source_observation=native_profile)
        observations.append(shadow)
    if native:
        return CellReading(
            "" if nonfinal else initial,
            bounds,
            observations,
            nonfinal
            or not bool(initial)
            or cell_source_status(original) not in {"legacy", "qualified"},
        )
    if isinstance(tokens, SourceTokens) and tokens.scan_bounds is None and not raw:
        # A native page's empty region is not automatically a scanned cell.
        # Check original pixels without invoking an OCR model; outlined/vector
        # ink must still take the existing bounded cell path below.
        image = cell_image(page, bounds, 400)
        if not np.any(image < 180):
            return CellReading("", bounds, observations, True)
    if kind == "plus":
        proof = observe_printed_crosses(
            render_cell_raster(page, bounds, 450, purpose="text").image, bounds
        )
        value = proof["text"]
        observations.append(proof)
        return CellReading(
            value,
            bounds,
            observations,
            not bool(value) or bool(native_value and value != native_value),
        )
    first_read = _ocr_cell(page, bounds, kind, 400)
    first = first_read.value
    observations.append(first_read.evidence(400, bounds))

    def original_id_conflict(candidate):
        return nonfinal or any(
            cell_source_conflict(o, candidate, kind)
            for o in observations
            if o.get("method") in {"native_cell", "page_ocr_cell"}
        )

    if (
        first
        and first == initial
        and cell_source_status(original) in {"legacy", "qualified"}
        and (not native_value or first == native_value)
        and not original_id_conflict(first)
    ):
        return CellReading(first, bounds, observations)
    second_read = _ocr_cell(page, bounds, kind, 600)
    second = second_read.value
    observations.append(second_read.evidence(600, bounds))
    agreed = bool(
        first
        and first == second
        and (
            cell_source_status(original) not in {"legacy", "qualified"}
            or not initial
            or first == initial
        )
        and (not native_value or first == native_value)
        and not original_id_conflict(first)
    )
    if kind in {"id", "label"} and not agreed and not nonfinal:
        from .cell_identity_proof import confirmed_identity_readings
        from .text_ocr.source_capture import refine_source_text

        observations[-2:] = refine_source_text(page, bounds, observations[-2:])
        candidate = _normalize(observations[-2]["text"], kind)
        if (
            candidate
            and not original_id_conflict(candidate)
            and confirmed_identity_readings(
                candidate, observations, caption=kind == "label"
            )
        ):
            return CellReading(candidate, bounds, observations)
    value = first if agreed else initial or first or second
    if kind in {"id", "label"} and not agreed:
        value = ""  # Candidates stay in raw observations, not the ID universe.
    return CellReading(
        value,
        bounds,
        observations,
        not agreed,
    )
