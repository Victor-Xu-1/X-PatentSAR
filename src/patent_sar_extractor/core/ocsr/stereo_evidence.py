"""One source-symbol risk gate shared by formal and research recognition.

Raster observations never assign atoms or absolute configuration. Unknown source
symbols can veto a contradictory model string, not repair it into a molecule.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from patent_sar_extractor.contracts import STEREO_EVIDENCE_VERSION

from .bond_strokes import is_periodic_wave, stroke_paths, thin_ink

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_PIXELS = 16 * 1024 * 1024


def observe_stereo_symbols(source: str | Path | bytes) -> dict[str, Any]:
    """Read the exact source crop once, bounding pixels, paths and retained boxes."""
    if isinstance(source, bytes):
        data = source
    else:
        with Path(source).open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise ValueError("Source crop is empty or exceeds 16 MiB")
    with Image.open(io.BytesIO(data)) as original:
        if original.width * original.height > MAX_SOURCE_PIXELS:
            raise ValueError("Source crop exceeds 16 million pixels")
        width, height = original.size
        if width < 8 or height < 8:
            raise ValueError("Source crop is too small for bond-symbol inspection")
        # Preserve transparency as white, never black foreground.
        original.thumbnail((768, 768))
        rgba = original.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        background.alpha_composite(rgba)
        image = background.convert("L")
        gray = np.asarray(image)
    import cv2

    _, ink = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    if np.mean(ink) > 0.4:
        raise ValueError("Source crop does not have a readable diagram background")
    boxes = []
    for points in stroke_paths(thin_ink(ink)):
        if not is_periodic_wave(points):
            continue
        x0, y0 = np.maximum(points.min(axis=0) - 2, 0)
        x1, y1 = np.minimum(points.max(axis=0) + 2, (gray.shape[1], gray.shape[0]))
        boxes.append(
            [
                round(float(x0 * width / gray.shape[1]), 2),
                round(float(y0 * height / gray.shape[0]), 2),
                round(float(x1 * width / gray.shape[1]), 2),
                round(float(y1 * height / gray.shape[0]), 2),
            ]
        )
        if len(boxes) > 64:
            raise ValueError(
                "Source diagram exceeds the unknown-bond observation budget"
            )
    return {
        "version": STEREO_EVIDENCE_VERSION,
        "image_sha256": hashlib.sha256(data).hexdigest(),
        "image_size": [width, height],
        "unknown_bond_boxes": boxes,
    }


def check_source_stereochemistry(qc: dict, evidence: dict[str, Any]) -> dict[str, Any]:
    """Compare risk observations to unmodified parsed chemistry, never guess parity."""
    defined = int(qc.get("assigned_chiral_centers", 0))
    defined_double = int(qc.get("assigned_double_bonds", 0))
    unassigned = int(qc.get("unassigned_chiral_centers", 0))
    unknown = len(evidence["unknown_bond_boxes"])
    status = "no_unknown_detected"
    reason = "Absence of a detected symbol is not proof of exact stereochemistry."
    if unknown and (defined or defined_double):
        status = (
            "conflict"
            if defined == 1 and not unassigned and not defined_double
            else "ambiguous"
        )
        reason = "Unknown source bond and defined model stereochemistry cannot be reconciled without atom correspondence."
    elif unknown and unassigned:
        status = "unknown_preserved"
        reason = "Source has an unknown-bond symbol; model retains unspecified centers. Atom correspondence and mixture/absolute assignment remain unverified."
    elif unknown:
        status = "ambiguous"
        reason = "Unknown source bond has no supported stereochemical representation in the model graph."
    return {
        **evidence,
        "status": status,
        "reason": reason,
        "assigned_centers": defined,
        "unassigned_centers": unassigned,
        "assigned_double_bonds": defined_double,
        "absolute_configuration_verified": False,
    }


def source_checked_qc(qc: dict, evidence: dict[str, Any]) -> dict:
    stereo = check_source_stereochemistry(qc, evidence)
    result = {**qc, "stereochemistry": stereo}
    if qc.get("quality_flag") == "ok" and stereo["status"] in {"conflict", "ambiguous"}:
        result["quality_flag"] = (
            "stereo_source_conflict"
            if stereo["status"] == "conflict"
            else "stereo_source_ambiguous"
        )
    return result
