"""Explicit bounded tail owners feed the existing caption and auxiliary replay."""

from patent_sar_extractor.contracts import CAPTION_TAIL_SOURCE_VERSION

from .caption_role_links import MAX_CONTINUATION_DEPTH
from .caption_tail_owners import caption_source_packet, validated_tail_caption_cells
from .source_evidence_identity import proof_id
from .text_ocr.source_inventory import MAX_SOURCE_CELLS


def _tails(ownership):
    role = ownership.get("caption_role")
    boundary = ownership.get("page_boundary")
    if isinstance(boundary, dict):
        tail = boundary["previous_tail"]
        previous = role if ownership["direction"] == "above" else boundary["other_role"]
        yield tail, previous
    depth = 0
    while isinstance(role, dict) and "continuation" in role:
        depth += 1
        if depth > MAX_CONTINUATION_DEPTH:
            raise ValueError("Original caption-tail ancestry exceeds its bound")
        link = role["continuation"]
        role = link["previous"]
        yield link["previous_tail"], role


def caption_tail_source_packets(bindings):
    seen = set()
    for binding in bindings:
        packet = binding.get("exact_caption_evidence")
        if not isinstance(packet, dict):
            continue
        ownership = packet.get("ownership")
        if not isinstance(ownership, dict):
            continue
        for tail, role in _tails(ownership):
            if isinstance(tail, dict) and set(tail) == {
                "page_no",
                "page_size",
                "window",
                "chunks",
                "page_grids",
                "diagrams",
            }:
                # Known historical transport contains no new cell owners to
                # replay. It still fails the current carry gate; keep history
                # readable, never manufacture or promote missing source proof.
                continue
            if (
                not isinstance(tail, dict)
                or type(tail.get("version")) is not int
                or tail["version"] != CAPTION_TAIL_SOURCE_VERSION
            ):
                raise ValueError("Unknown original caption-tail source version")
            for owner in validated_tail_caption_cells(tail["caption_cells"], role):
                key = (
                    owner["page_no"],
                    proof_id({"status": "original_caption_tail_cell", "cell": owner}),
                )
                if key in seen:
                    continue
                seen.add(key)
                if len(seen) > MAX_SOURCE_CELLS:
                    raise ValueError("Original caption-tail sources exceed their bound")
                yield (
                    f"caption boundary p{owner['page_no']}",
                    caption_source_packet(owner),
                )


def caption_tail_text_cells(bindings):
    for _name, packet in caption_tail_source_packets(bindings):
        for observation in packet["observations"]:
            yield packet["page_no"], observation
