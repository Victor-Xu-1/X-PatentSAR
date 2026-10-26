"""Conserve qualified original native words during complete optical title reads."""

import re

from .native_window_coverage import (
    native_window_complete,
    native_window_text_complete,
)
from .native_window_rules import boundary_rule_path
from .printed_identifiers import identifier_width
from .source_geometry import overlaps
from .source_observations import source_observation_status
from .source_section_roles import heading_members, section_heading


def heading_literal(value):
    return " ".join(identifier_width(value).split()).casefold()


def native_heading_agrees(proof, whole):
    """A partial layer is a retained constraint, never an incomplete whole vote.

    A current complete optical reading must ADD the omitted source text while
    preserving every whole native word, original member and visible paint. It
    cannot merely echo the known subset, embed/change an identifier or outvote
    a complete native title. Actual-original replay still owns all paint/pixels.
    """
    native, window = proof["native_source"], proof.get("native_window")
    if not native["text"].strip():
        return True
    if source_observation_status(
        native, proof["bbox"], native["text"]
    ) != "qualified" or not native_window_text_complete(window, native):
        return False
    known, complete = heading_literal(native["text"]), heading_literal(whole)
    if native_window_complete(window, native):
        return known == complete
    if len(known) >= len(complete) or any(
        "native_paint" not in t for t in native["tokens"]
    ):
        return False
    retained = native["tokens"]
    box = [
        min(t["bbox"][0] for t in retained),
        min(t["bbox"][1] for t in retained),
        max(t["bbox"][2] for t in retained),
        max(t["bbox"][3] for t in retained),
    ]
    sides = set()
    for paint in window["paints"]:
        if paint["kind"] == "fill-text" or (
            window["boundary_source_id"] is not None
            and paint["kind"] == "stroke-path"
            and boundary_rule_path(paint["rule_path"], window["bbox"])
        ):
            continue
        if any(overlaps(paint["bbox"], token["bbox"]) for token in retained):
            return False  # Hidden/covered/intersected native text is not a waiver.
        mark = paint["bbox"]
        if mark[2] <= box[0] or mark[3] <= box[1]:
            sides.add("before")
        elif mark[0] >= box[2] or mark[1] >= box[3]:
            sides.add("after")
        else:
            return False  # Interleaved ink cannot acquire an arbitrary word slot.
    # Whole-word boundaries preserve suffixes, punctuation and literal IDs. A
    # repeated match cannot select one of several physical claims arbitrarily.
    matches = list(re.finditer(r"(?<!\w)" + re.escape(known) + r"(?!\w)", complete))
    if len(matches) != 1:
        return False
    match = matches[0]
    if (
        "before" in sides
        and not any(c.isalnum() for c in complete[: match.start()])
        or "after" in sides
        and not any(c.isalnum() for c in complete[match.end() :])
    ):
        return False  # Added punctuation or the wrong side cannot read a prefix.
    original, selected = section_heading(native["text"]), section_heading(whole)
    return not (
        original is not None
        and (
            selected is None
            or original["label_kind"] != selected["label_kind"]
            or heading_members(original) != heading_members(selected)
            or original["role"] != "compound_heading"
            and selected["role"] != original["role"]
        )
    )
