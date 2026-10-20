"""Prove external tail witnesses with existing literal closed-caption readings."""

from itertools import pairwise

from .caption_source_windows import caption_windows
from .cell_identity_proof import confirmed_identity_readings
from .source_cell_claims import cell_source_status
from .source_evidence_identity import proof_id
from .source_observations import source_observation_status


def _witness_key(origin, token):
    return origin, proof_id(
        {"status": "original_caption_boundary_witness", "token": token}
    )


def caption_source_packet(owner):
    """Adapt a retained closed cell to the one ordinary original-caption replay."""
    return {
        "page_no": owner["page_no"],
        "bbox": owner["bbox"],
        "reading_bbox": owner["bbox"],
        "observations": owner["observations"],
        "ownership": {"kind": "ruled_caption"},
    }


def validated_tail_caption_cells(cells, role):
    if not isinstance(cells, list) or len(cells) > 64:
        raise ValueError("Unbounded original caption-tail cell inventory")
    axes, seen = role["grid_axes"], set()
    columns = set(pairwise(axes["xs"]))
    for owner in cells:
        if not isinstance(owner, dict) or set(owner) != {
            "page_no",
            "bbox",
            "label",
            "bare",
            "observations",
        }:
            raise ValueError("Malformed original caption-tail cell")
        box, observations = owner["bbox"], owner["observations"]
        if (
            type(owner["page_no"]) is not int
            or owner["page_no"] != role["page_no"]
            or not isinstance(box, list)
            or len(box) != 4
            or (box[0], box[2]) not in columns
            or box[1::2] != axes["ys"][-2:]
            or tuple(box) in seen
            or type(owner["bare"]) is not bool
            or role["role"] != "compound"
            or not isinstance(owner["label"], str)
            or not 1 <= len(owner["label"]) <= 128
            or caption_windows(caption_source_packet(owner)) is None
            or not confirmed_identity_readings(
                owner["label"], observations, caption=not owner["bare"]
            )
        ):
            raise ValueError("Unproved original caption-tail cell ownership")
        seen.add(tuple(box))
    return cells


def caption_witness_keys(cells):
    """Call-local exact original-token index, not a second source inventory."""
    return {
        _witness_key(profile["origin"], token)
        for owner in cells
        for reading in owner["observations"]
        if isinstance(profile := reading.get("source_observation"), dict)
        and cell_source_status(reading) != "invalid"
        for token in profile.get("tokens", [])
    }


def observe_tail_caption_cells(captions, role, chunks):
    """Retain only needed, already read cells; never start another OCR pass."""
    witnesses = {
        _witness_key(source["origin"], token)
        for chunk in chunks
        for source in chunk["sources"]
        for token in source.get("boundary_tokens", [])
    }
    result = []
    for item in captions:
        if item["review"]:
            continue
        owner = {
            "page_no": item["page"],
            "bbox": list(item["bbox"]),
            "label": item["label"],
            "bare": item["bare"],
            "observations": list(item["observations"]),
        }
        try:
            validated_tail_caption_cells([owner], role)
        except (KeyError, TypeError, ValueError):
            continue  # The unresolved original item remains in ordinary issues.
        if caption_witness_keys([owner]) & witnesses:
            result.append(owner)
    return result


def qualified_tail_source(packet, witnesses):
    """Body text stays strict; only independently owned neighbour witnesses resolve.

    The original packet is never modified or upgraded. This call-local view
    answers only whether its body lane can prove a catalogue carry. Every
    removed neighbour must occur unchanged in a qualified closed caption's
    original source profile; original-pixel replay still checks those cells.
    """
    if (
        source_observation_status(packet, packet.get("bbox"), packet.get("text"))
        == "invalid"
    ):
        return False
    if any(
        _witness_key(packet["origin"], token) not in witnesses
        for token in packet.get("boundary_tokens", [])
    ):
        return False
    view = {
        **packet,
        "boundary_tokens": [],
        "status": "qualified" if packet["tokens"] else "empty",
    }
    return source_observation_status(view, view["bbox"], view["text"]) in {
        "qualified",
        "empty",
    }
