"""Complete native-window paint ownership, not visibility of a successful subset."""

import math
import re

import fitz

from .cell_frame_proof import inside_box
from .native_window_rules import boundary_rule_path, original_rule_path
from .source_cell_pixels import observe_closed_cell
from .source_evidence_identity import proof_id
from .source_geometry import overlaps
from .source_observations import source_observation_status
from .source_paint_visibility import (
    original_paint_view,
    source_stroke_hits,
)

MAX_WINDOW_PAINTS = 4096
MAX_WINDOW_PRIMITIVES = 20_000


def native_cell_packet(page, profile, *, paint_view=None):
    """One current native observation envelope for all existing cell callers."""
    return {
        "method": "native_cell",
        "text": profile["text"],
        "bbox": list(profile["bbox"]),
        "source_observation": profile,
        "native_window": observe_native_window(
            page, profile["bbox"], paint_view=paint_view
        ),
    }


def observe_native_window(page, bounds, *, paint_view=None):
    """Retain every intersecting paint, without cropping to recognized words.

    This is a native fast-path witness, not another text reader. Over-budget
    sources retain an explicit refusal; the existing complete pixel path still
    owns any optical observation. Actual-original replay recomputes these facts.
    """
    if not inside_box(bounds, [0, 0, page.rect.width, page.rect.height]):
        raise ValueError("Native source window leaves its original page")
    # Reuse the existing visibility authority, including its document/edit guard.
    paint_view = original_paint_view(page, paint_view)
    if paint_view is None:
        raise ValueError("Native paint observation belongs to another original page")
    selected = []
    count = 0
    primitives = 0
    for order, (kind, original) in enumerate(paint_view.paints):
        box = list(fitz.Rect(original) * page.rotation_matrix)
        if not overlaps(box, bounds) or (
            kind == "stroke-path"
            and not source_stroke_hits(page, paint_view.paths.get(order), bounds)
        ):
            continue
        count += 1
        if count <= MAX_WINDOW_PAINTS and primitives <= MAX_WINDOW_PRIMITIVES:
            rule = (
                original_rule_path(paint_view.paths.get(order), page)
                if kind == "stroke-path"
                else None
            )
            primitives += len(rule["segments"]) if rule is not None else 1
            selected.append(
                {
                    "seqno": order,
                    "kind": kind,
                    "bbox": box,
                    "text": "".join(
                        text
                        for text, glyph in paint_view.glyphs.get(order, ())
                        if overlaps(glyph, bounds)
                    ),
                    "rule_path": rule,
                }
            )
    refusal = (
        "paint_budget"
        if count > MAX_WINDOW_PAINTS
        else "primitive_budget"
        if primitives > MAX_WINDOW_PRIMITIVES
        else None
    )
    boundary = refusal is None and any(
        paint["kind"] == "stroke-path"
        and boundary_rule_path(paint["rule_path"], bounds)
        for paint in selected
    )
    pixels = observe_closed_cell(page, list(bounds)) if boundary else None
    return {
        "version": 1,
        "bbox": list(bounds),
        "page_size": [page.rect.width, page.rect.height],
        "paint_count": count,
        "paints": selected if refusal is None else [],
        "refusal": refusal,
        # Native observations already require actual-original replay. Pin the
        # whole strict pixel witness, not hundreds of duplicate rendered cells.
        # This is never a standalone admission flag: replay re-observes the same
        # closed source and compares this exact content identity before use.
        "boundary_source_id": proof_id(
            {"status": "original_native_boundary", "pixels": pixels}
        )
        if pixels is not None
        else None,
    }


def valid_native_window(packet, bounds):
    if (
        not inside_box(bounds, [-1_000_000, -1_000_000, 1_000_000, 1_000_000])
        or not isinstance(packet, dict)
        or set(packet)
        != {
            "version",
            "bbox",
            "page_size",
            "paint_count",
            "paints",
            "refusal",
            "boundary_source_id",
        }
        or type(packet["version"]) is not int
        or packet["version"] != 1
        or packet["bbox"] != list(bounds)
        or not isinstance(packet["page_size"], list)
        or len(packet["page_size"]) != 2
        or any(
            type(v) not in {int, float} or not math.isfinite(v) or v <= 0
            for v in packet["page_size"]
        )
        or not inside_box(bounds, [0, 0, *packet["page_size"]])
        or type(packet["paint_count"]) is not int
        or not 0 <= packet["paint_count"] <= 100_000
        or not isinstance(packet["paints"], list)
    ):
        return False
    if packet["paint_count"] > MAX_WINDOW_PAINTS:
        return (
            packet["refusal"] == "paint_budget"
            and packet["paints"] == []
            and packet["boundary_source_id"] is None
        )
    if packet["refusal"] == "primitive_budget":
        return packet["paints"] == [] and packet["boundary_source_id"] is None
    if packet["refusal"] is not None or len(packet["paints"]) != packet["paint_count"]:
        return False
    previous = -1
    primitives = 0
    characters = 0
    for paint in packet["paints"]:
        if not isinstance(paint, dict) or set(paint) != {
            "seqno",
            "kind",
            "bbox",
            "text",
            "rule_path",
        }:
            return False
        box = paint["bbox"]
        if (
            type(paint["seqno"]) is not int
            or not previous < paint["seqno"] < 100_000
            or not isinstance(paint["kind"], str)
            or not 0 < len(paint["kind"]) <= 64
            or not isinstance(paint["text"], str)
            or len(paint["text"]) > 1_000_000
            or paint["kind"] != "stroke-path"
            and paint["rule_path"] is not None
            or not isinstance(box, list)
            or len(box) != 4
            or any(type(v) not in {int, float} or not math.isfinite(v) for v in box)
            or not box[0] < box[2]
            or not box[1] < box[3]
            or not overlaps(box, bounds)
        ):
            return False
        rule = paint["rule_path"]
        if rule is not None and (
            not isinstance(rule, dict)
            or set(rule) != {"width", "segments"}
            or not isinstance(rule["segments"], list)
        ):
            return False
        primitives += len(rule["segments"]) if rule is not None else 1
        characters += len(paint["text"])
        if primitives > MAX_WINDOW_PRIMITIVES or characters > 1_000_000:
            return False
        previous = paint["seqno"]
    boundary = packet["boundary_source_id"]
    return (
        boundary is None
        or isinstance(boundary, str)
        and re.fullmatch(r"[a-f0-9]{64}", boundary) is not None
    )


def native_window_text_complete(packet, native):
    """All original native glyphs are retained, independent of other source ink."""
    if (
        not isinstance(native, dict)
        or native.get("origin") != "native"
        or source_observation_status(native, native.get("bbox"), native.get("text"))
        != "qualified"
        or not valid_native_window(packet, native["bbox"])
        or packet["refusal"] is not None
    ):
        return False
    paints = {
        paint["seqno"]: paint
        for paint in packet["paints"]
        if paint["kind"] == "fill-text"
    }
    if any(
        "native_paint" in token
        and (
            token["native_paint"]["seqno"] not in paints
            or token["native_paint"]["bbox"]
            != paints[token["native_paint"]["seqno"]]["bbox"]
        )
        for token in native["tokens"]
    ):
        return False
    # A PDF text operation need not encode spaces/newlines between separately
    # positioned glyphs. Compare the complete original character order only for
    # paint coverage; native word/row boundaries and raw scientific strings stay
    # under the unchanged SourceObservation/parser authority.
    return "".join(
        character
        for paint in paints.values()
        for character in paint["text"]
        if not character.isspace()
    ) == "".join(
        character
        for token in native["tokens"]
        for character in token["text"]
        if not character.isspace()
    )


def native_window_complete(packet, native):
    """A native vote needs the WHOLE paint inventory and every original word."""
    if not native_window_text_complete(packet, native):
        return False
    return all(
        paint["kind"] == "fill-text"
        or packet["boundary_source_id"] is not None
        and paint["kind"] == "stroke-path"
        and boundary_rule_path(paint["rule_path"], packet["bbox"])
        for paint in packet["paints"]
    )
