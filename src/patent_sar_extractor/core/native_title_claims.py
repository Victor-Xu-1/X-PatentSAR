"""Exact native word anchors and original ink slots, never semantic OCR votes."""

import re

from .native_window_coverage import native_window_complete, native_window_text_complete
from .native_window_rules import boundary_rule_path
from .printed_identifiers import identifier_width
from .source_cell_tokens import cell_lines
from .source_geometry import overlaps


def title_literal(value):
    return " ".join(identifier_width(value).split()).casefold()


def _ink_slots(window, native):
    rows = cell_lines(native["tokens"], native["bbox"])
    ordered = [token for row in rows for token in row]
    slots, offset = set(), 0
    row_ranges = []
    for row in rows:
        row_ranges.append(
            (
                offset,
                row,
                min(t["bbox"][1] for t in row),
                max(t["bbox"][3] for t in row),
            )
        )
        offset += len(row)
    for paint in window["paints"]:
        if paint["kind"] == "fill-text" or (
            window["boundary_source_id"] is not None
            and paint["kind"] == "stroke-path"
            and boundary_rule_path(paint["rule_path"], window["bbox"])
        ):
            continue
        mark = paint["bbox"]
        if any(overlaps(mark, token["bbox"]) for token in ordered):
            return None
        lanes = [
            (start, row)
            for start, row, top, bottom in row_ranges
            if min(bottom, mark[3]) > max(top, mark[1])
        ]
        if len(lanes) == 1:
            start, row = lanes[0]
            before = [i for i, token in enumerate(row) if token["bbox"][2] <= mark[0]]
            after = [i for i, token in enumerate(row) if token["bbox"][0] >= mark[2]]
            left, right = (
                (max(before) + 1 if before else 0),
                (min(after) if after else len(row)),
            )
            if left != right:
                return None
            slots.add(start + left)
        elif lanes:
            return None
        else:
            before = [
                start + len(row)
                for start, row, _top, bottom in row_ranges
                if bottom <= mark[1]
            ]
            after = [
                start for start, _row, top, _bottom in row_ranges if top >= mark[3]
            ]
            left, right = max(before, default=0), min(after, default=len(ordered))
            if left != right:
                return None
            slots.add(left)
    return ordered, slots


def native_title_agrees(proof, whole):
    native, window = proof["native_source"], proof["native_window"]
    if not native["text"].strip():
        return True
    if not native_window_text_complete(window, native):
        return False
    known, selected = title_literal(native["text"]), title_literal(whole)
    if native_window_complete(window, native):
        return known == selected
    if len(known) >= len(selected) or any(
        "native_paint" not in t for t in native["tokens"]
    ):
        return False
    anchors = _ink_slots(window, native)
    if anchors is None:
        return False
    tokens, slots = anchors

    def gap_agrees(index, literal):
        return (
            any(c.isalnum() for c in literal) if index in slots else not literal.strip()
        )

    states, work = {0: 1}, 0
    for index, token in enumerate(tokens):
        matches = list(
            re.finditer(
                r"(?<!\w)" + re.escape(title_literal(token["text"])) + r"(?!\w)",
                selected,
            )
        )
        updated = {}
        for end, count in states.items():
            for match in matches:
                work += 1
                if work > 131072:
                    return False
                if match.start() >= end and gap_agrees(
                    index, selected[end : match.start()]
                ):
                    updated[match.end()] = min(2, updated.get(match.end(), 0) + count)
        states = updated
        if not states:
            return False
    return (
        sum(
            count
            for end, count in states.items()
            if gap_agrees(len(tokens), selected[end:])
        )
        == 1
    )
