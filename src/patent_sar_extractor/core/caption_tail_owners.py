"""Prove external tail witnesses with existing literal closed-caption readings."""

from itertools import pairwise

from .caption_cell_pixels import observe_closed_caption_scope
from .caption_cell_scope import physical_caption_readings, valid_closed_caption_scope
from .caption_source_windows import caption_windows
from .cell_frame_proof import inside_box
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
        **({"closed_scope": owner["closed_scope"]} if "closed_scope" in owner else {}),
    }


def validated_tail_caption_cells(cells, role, *, allow_physical=True):
    if not isinstance(cells, list) or len(cells) > 64:
        raise ValueError("Unbounded original caption-tail cell inventory")
    axes, seen = role["grid_axes"], set()
    columns = set(pairwise(axes["xs"]))
    for owner in cells:
        identity = {"page_no", "bbox", "label", "bare", "observations"}
        physical = {"page_no", "bbox", "observations", "closed_scope"}
        if not isinstance(owner, dict) or set(owner) not in (identity, physical):
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
            or role["role"] != "compound"
            or caption_windows(caption_source_packet(owner)) is None
        ):
            raise ValueError("Unproved original caption-tail cell ownership")
        if set(owner) == identity:
            if (
                type(owner["bare"]) is not bool
                or not isinstance(owner["label"], str)
                or not 1 <= len(owner["label"]) <= 128
                or not confirmed_identity_readings(
                    owner["label"], observations, caption=not owner["bare"]
                )
            ):
                raise ValueError("Unproved original caption-tail identity")
        elif (
            not allow_physical
            or not physical_caption_readings(observations, box)
            or not valid_closed_caption_scope(owner["closed_scope"], box)
        ):
            raise ValueError("Unproved original closed-caption physical scope")
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
        if "closed_scope" not in owner
        or inside_box(token.get("bbox"), owner["closed_scope"]["bounds"])
    }


def observe_tail_caption_cells(page, captions, role, chunks):
    """Keep label quality separate from replayed closed-cell physical scope."""
    witnesses = {
        _witness_key(source["origin"], token): token
        for chunk in chunks
        for source in chunk["sources"]
        for token in source.get("boundary_tokens", [])
    }
    result = []
    for item in captions:
        owner = {
            "page_no": item["page"],
            "bbox": list(item["bbox"]),
            "label": item["label"],
            "bare": item["bare"],
            "observations": list(item["observations"]),
        }
        matching = caption_witness_keys([owner]) & witnesses.keys()
        if not matching:
            continue
        try:
            if item["review"]:
                raise ValueError("Unresolved caption identity")
            validated_tail_caption_cells([owner], role)
        except (KeyError, TypeError, ValueError):
            # This records no label/annotation interpretation. Actual unknown
            # ink outside the closed cell is refused by independent pixel views.
            physical = {key: owner[key] for key in ("page_no", "bbox", "observations")}
            if not physical_caption_readings(
                physical["observations"], physical["bbox"]
            ):
                continue
            scope = observe_closed_caption_scope(
                page, physical["bbox"], [witnesses[key] for key in sorted(matching)]
            )
            if scope is None:
                continue
            physical["closed_scope"] = scope
            try:
                validated_tail_caption_cells([physical], role)
            except (KeyError, TypeError, ValueError):
                continue
            owner = physical
        result.append(owner)
    return result


def qualified_tail_source(packet, witnesses):
    """Body text stays strict; only independently owned neighbour witnesses resolve.

    The original packet is never modified or upgraded. This call-local view
    answers only whether its body lane can prove a catalogue carry. Every
    removed neighbour must occur unchanged in a replayed closed caption's
    original source profile. Physical-only scopes qualify no text or identity.
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
