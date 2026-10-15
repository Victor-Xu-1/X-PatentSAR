"""Bounded original native/raster cell provenance; never scientific inference."""

import math
from collections.abc import Mapping

from .cell_ocr_scores import confidence_value
from .ocr_claims import qualified_text_runs
from .source_cell_tokens import cell_lines, cell_text, cell_tokens, crosses_cell
from .source_geometry import SourceTokens

MAXIMUM_TOKENS = 512


def _box(value, *, original=False):
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(
            type(v) in {int, float}
            and math.isfinite(v)
            and (-1_000_000 if original else 0) <= v <= 1_000_000
            for v in value
        )
        and value[0] < value[2]
        and value[1] < value[3]
    )


def source_cell_observation(tokens, bounds, *, native=False):
    """Legacy caller strings keep their old strict contract, never a hint waiver."""
    if not isinstance(tokens, SourceTokens):
        return None
    if not _box(bounds):
        raise ValueError("Invalid original source-cell bounds")
    selected = cell_tokens(tokens.native_tokens if native else tokens, bounds)
    if len(selected) > MAXIMUM_TOKENS:
        raise ValueError("Original source-cell token budget exceeded")
    retained = []
    for part in selected:
        if (
            not isinstance(part.get("text"), str)
            or len(part["text"]) > 4096
            or not _box(part.get("bbox"), original=True)
            or any(
                type(part.get(k)) not in {int, float} or not math.isfinite(part[k])
                for k in ("x", "y")
            )
        ):
            raise ValueError("Malformed original source-cell token")
        available = "confidence" in part
        score = confidence_value(part.get("confidence")) if available else 0.0
        retained.append(
            {
                "text": part["text"],
                "x": part["x"],
                "y": part["y"],
                "bbox": list(part["bbox"]),
                "source": part.get("source", "native" if native else "raster"),
                "geometry_space": "rendered",
                "confidence": score if score is not None else 0.0,
                "confidence_available": available,
                "confidence_valid": score is not None
                and part.get("confidence_valid", True) is True,
            }
        )
    packet = {
        "schema_version": 1,
        "origin": "native" if native else "raster",
        "coordinate_space": "rendered_pdf_points",
        "bbox": list(bounds),
        "tokens": retained,
        "text": cell_text(retained, bounds),
    }
    packet["status"] = _status(packet)
    return packet


def _status(packet):
    parts = packet["tokens"]
    if any(part["confidence_valid"] is not True for part in parts):
        return "invalid"
    if not parts:
        return "empty"
    if crosses_cell(parts, packet["bbox"]):
        return "unqualified"
    return (
        "qualified"
        if all(
            part["confidence_available"] and part["confidence"] >= 0.85
            for part in parts
        )
        else "unqualified"
    )


def source_observation_status(packet, bounds, text):
    """Replay scope, whole original text, scores and status; do not trust flags."""
    if (
        not isinstance(packet, Mapping)
        or type(packet.get("schema_version")) is not int
        or packet["schema_version"] != 1
        or packet.get("coordinate_space") != "rendered_pdf_points"
        or packet.get("origin") not in {"native", "raster"}
        or not _box(packet.get("bbox"))
        or not _box(bounds)
        or tuple(packet["bbox"]) != tuple(bounds)
        or packet.get("text") != text
        or not isinstance(packet.get("tokens"), list)
        or len(packet["tokens"]) > MAXIMUM_TOKENS
    ):
        return "invalid"
    for part in packet["tokens"]:
        if (
            not isinstance(part, Mapping)
            or not isinstance(part.get("text"), str)
            or len(part["text"]) > 4096
            or not _box(part.get("bbox"), original=True)
            or part.get("geometry_space") != "rendered"
            or part.get("source") not in {"native", "raster"}
            or type(part.get("confidence_available")) is not bool
            or type(part.get("confidence_valid")) is not bool
            or confidence_value(part.get("confidence")) is None
            or not part["confidence_available"]
            and part["confidence"] != 0
            or any(
                type(part.get(k)) not in {int, float} or not math.isfinite(part[k])
                for k in ("x", "y")
            )
            or not packet["bbox"][0] <= part["x"] < packet["bbox"][2]
            or not packet["bbox"][1] <= part["y"] < packet["bbox"][3]
            or packet["origin"] == "native"
            and (
                part["source"] != "native"
                or not part["confidence_available"]
                or part["confidence"] != 1
            )
        ):
            return "invalid"
    if cell_text(packet["tokens"], bounds) != text:
        return "invalid"
    status = _status(packet)
    return status if packet.get("status") == status else "invalid"


def source_claim_runs(packet):
    """Qualified original fragments, without borrowing cross-cell ownership."""
    if (
        not isinstance(packet, Mapping)
        or source_observation_status(packet, packet.get("bbox", ()), packet.get("text"))
        == "invalid"
    ):
        return None
    parts = [
        {**part, "confidence": 0.0} if crosses_cell([part], packet["bbox"]) else part
        for part in packet["tokens"]
    ]
    runs = []
    for line in cell_lines(parts, packet["bbox"]):
        observed = qualified_text_runs(line, maximum_parts=MAXIMUM_TOKENS)
        if observed is None:
            return None
        runs.extend(observed)
    return tuple(runs)
