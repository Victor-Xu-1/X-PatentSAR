"""Bounded original native/raster cell provenance; never scientific inference."""

import math
from collections.abc import Mapping

from .cell_ocr_scores import confidence_value
from .native_paint_geometry import valid_native_paint
from .ocr_claims import qualified_text_runs
from .source_cell_tokens import (
    cell_intersections,
    cell_lines,
    cell_text,
    cell_tokens,
    crosses_cell,
)
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
    inventory = tokens.native_tokens if native else tokens
    selected = cell_tokens(inventory, bounds)
    owned_ids = {id(part) for part in selected}
    boundary = [
        part
        for part in cell_intersections(inventory, bounds)
        if id(part) not in owned_ids
    ]
    if len(selected) + len(boundary) > MAXIMUM_TOKENS:
        raise ValueError("Original source-cell token budget exceeded")
    retained = []
    for part in [*selected, *boundary]:
        if (
            not isinstance(part.get("text"), str)
            or len(part["text"]) > 4096
            or not _box(part.get("bbox"), original=True)
            or "native_paint" in part
            and not valid_native_paint(part)
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
                **(
                    {
                        "native_paint": {
                            **part["native_paint"],
                            "bbox": list(part["native_paint"]["bbox"]),
                        }
                    }
                    if valid_native_paint(part)
                    else {}
                ),
            }
        )
    packet = {
        "schema_version": 2,
        "origin": "native" if native else "raster",
        "coordinate_space": "rendered_pdf_points",
        "bbox": list(bounds),
        "tokens": retained[: len(selected)],
        "boundary_tokens": retained[len(selected) :],
        "text": cell_text(retained[: len(selected)], bounds),
    }
    packet["status"] = _status(packet)
    return packet


def _status(packet):
    parts = packet["tokens"]
    boundary = packet.get("boundary_tokens", [])
    if any(part["confidence_valid"] is not True for part in [*parts, *boundary]):
        return "invalid"
    if boundary:
        return "unqualified"
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
        or packet["schema_version"] not in {1, 2}
        or packet["schema_version"] == 1
        and "boundary_tokens" in packet
        or packet["schema_version"] == 2
        and not isinstance(packet.get("boundary_tokens"), list)
        or packet.get("coordinate_space") != "rendered_pdf_points"
        or packet.get("origin") not in {"native", "raster"}
        or not _box(packet.get("bbox"))
        or not _box(bounds)
        or tuple(packet["bbox"]) != tuple(bounds)
        or packet.get("text") != text
        or not isinstance(packet.get("tokens"), list)
        or len(packet["tokens"]) + len(packet.get("boundary_tokens", []))
        > MAXIMUM_TOKENS
    ):
        return "invalid"
    for part in [*packet["tokens"], *packet.get("boundary_tokens", [])]:
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
            or "native_paint" in part
            and not valid_native_paint(part)
            or not part["confidence_available"]
            and part["confidence"] != 0
            or any(
                type(part.get(k)) not in {int, float} or not math.isfinite(part[k])
                for k in ("x", "y")
            )
            or packet["origin"] == "native"
            and (
                part["source"] != "native"
                or not part["confidence_available"]
                or part["confidence"] != 1
            )
        ):
            return "invalid"
    if len(cell_tokens(packet["tokens"], bounds)) != len(packet["tokens"]):
        return "invalid"
    boundary = packet.get("boundary_tokens", [])
    if (
        cell_tokens(boundary, bounds)
        or len(cell_intersections(boundary, bounds)) != len(boundary)
        or any(part in packet["tokens"] for part in boundary)
    ):
        return "invalid"
    if cell_text(packet["tokens"], bounds) != text:
        return "invalid"
    status = _status(packet)
    return status if packet.get("status") == status else "invalid"


def _copy_token(part):
    copied = {**part, "bbox": list(part["bbox"])}
    if "native_paint" in part:
        copied["native_paint"] = {
            **part["native_paint"],
            "bbox": list(part["native_paint"]["bbox"]),
        }
    return copied


def project_source_observation(packet, bounds):
    """A smaller owned observation retains exact original tokens and status."""
    if source_observation_status(
        packet, packet.get("bbox"), packet.get("text")
    ) == "invalid" or not _box(bounds):
        raise ValueError("Invalid original observation projection")
    parent = packet["bbox"]
    if not (
        parent[0] <= bounds[0] < bounds[2] <= parent[2]
        and parent[1] <= bounds[1] < bounds[3] <= parent[3]
    ):
        raise ValueError("Projected source leaves its original observation")
    inventory = [*packet["tokens"], *packet.get("boundary_tokens", [])]
    retained = [_copy_token(part) for part in cell_tokens(inventory, bounds)]
    boundary = [
        _copy_token(part)
        for part in cell_intersections(inventory, bounds)
        if not cell_tokens([part], bounds)
    ]
    projected = {
        "schema_version": packet["schema_version"],
        "origin": packet["origin"],
        "coordinate_space": packet["coordinate_space"],
        "bbox": list(bounds),
        "tokens": retained,
        "text": cell_text(retained, bounds),
        **({"boundary_tokens": boundary} if packet["schema_version"] == 2 else {}),
    }
    projected["status"] = _status(projected)
    if "original_titles" in packet:
        records = packet["original_titles"]
        if not isinstance(records, list) or len(records) > 128:
            raise ValueError("Malformed original title source inventory")
        projected["original_titles"] = records
    if "title_context" in packet:
        projected["title_context"] = packet["title_context"]
    return projected


def source_claim_runs(packet, *, tokens=None):
    """Qualified original fragments, without borrowing cross-cell ownership."""
    if (
        not isinstance(packet, Mapping)
        or source_observation_status(packet, packet.get("bbox", ()), packet.get("text"))
        == "invalid"
    ):
        return None
    selected = packet["tokens"] if tokens is None else tokens
    if (
        not isinstance(selected, (list, tuple))
        or len(selected) > MAXIMUM_TOKENS
        or any(not any(part is old for old in packet["tokens"]) for part in selected)
    ):
        return None
    if packet.get("boundary_tokens"):
        return ()  # A retained neighbour witness cannot authorize a partial claim.
    parts = [
        {**part, "confidence": 0.0} if crosses_cell([part], packet["bbox"]) else part
        for part in selected
    ]
    runs = []
    for line in cell_lines(parts, packet["bbox"]):
        observed = qualified_text_runs(line, maximum_parts=MAXIMUM_TOKENS)
        if observed is None:
            return None
        runs.extend(observed)
    return tuple(runs)
