"""Ordered literal comparison against an independently observed whole caption."""

import re
from collections.abc import Mapping
from itertools import combinations

from .cell_ocr_line_groups import bounds, group_text_lines
from .compound_caption import prefixed_label
from .printed_identifiers import (
    LABEL_KIND,
    LABEL_PREFIX,
    identifier_key,
    identifier_width,
)

_ROLE = re.compile(rf"{LABEL_PREFIX}", re.IGNORECASE)
_KIND = re.compile(LABEL_KIND, re.IGNORECASE)


def overlapping_literal_id_letters(raw, observed, boxes):
    """A letter inside a qualified whole-ID detector box is not a second copy.

    Only the already observed complete caption supplies the ID. The numeric
    whole-ID detector must agree literally; separate letters, foreign characters,
    complete prefixed claims and other rows retain their existing conflict gates.
    Observations and boxes have already passed the shared qualification checks.
    """
    label = prefixed_label(raw)
    duplicates = set()
    if not label:
        return duplicates
    for index, part in observed:
        letter = identifier_width(part["text"]).strip().upper().removesuffix(".")
        if not re.fullmatch(r"[A-Z]+", letter) or letter not in label:
            continue
        small = boxes[index]
        x, y = (small[0] + small[2]) / 2, (small[1] + small[3]) / 2
        for other_index, other in observed:
            if (
                other_index == index
                or not any(char.isnumeric() for char in other["text"])
                or identifier_key(other["text"], terminal_period=True) != label
            ):
                continue
            whole = boxes[other_index]
            height = min(small[3] - small[1], whole[3] - whole[1])
            if (
                whole[0] <= x <= whole[2]
                and whole[1] <= y <= whole[3]
                and small[2] - small[0] <= whole[2] - whole[0]
                and min(small[3], whole[3]) - max(small[1], whole[1]) >= height / 2
            ):
                duplicates.add(index)
    return duplicates


def overlapping_role_locators(raw, observed, boxes):
    """Same-role punctuation may be a detector boundary, never an identifier.

    The independently read whole caption and a qualified complete identifier
    across that exact right edge must agree. Only the nonnumeric role locator is
    exempted; every independent numeric/letter/complete-caption claim remains.
    """
    role = _KIND.match(raw)
    label = prefixed_label(raw)
    if role is None or not label:
        return set()
    locators = set()
    for index, part in observed:
        detected = _KIND.match(part["text"])
        if (
            detected is None
            or detected.group().casefold() != role.group().casefold()
            or any(char.isalnum() for char in part["text"][detected.end() :])
        ):
            continue
        left = boxes[index]
        for other_index, other in observed:
            if (
                other_index == index
                or identifier_key(other["text"], terminal_period=True) != label
            ):
                continue
            right = boxes[other_index]
            height = min(left[3] - left[1], right[3] - right[1])
            if (
                left[0] < right[0] < left[2] - 1 < right[2] - 1
                and min(left[3], right[3]) - max(left[1], right[1]) >= height / 2
            ):
                locators.add(index)
    return locators


def truncated_caption_boundary(label, index, observed, boxes):
    """A same-row numeric box may prove the detector's right edge is incomplete.

    Only a literal prefix and an independently retained qualified whole number
    across that exact boundary qualify. Disjoint, contained, weak or different
    IDs cannot waive a complete prefixed claim. No new identifier is constructed.
    """
    candidate = prefixed_label(dict(observed)[index]["text"])
    if not candidate or candidate == label or not label.startswith(candidate):
        return False
    left = boxes[index]
    for other_index, part in observed:
        right = boxes[other_index]
        height = min(left[3] - left[1], right[3] - right[1])
        if (
            other_index != index
            and identifier_key(part["text"], terminal_period=True) == label
            and left[0] < right[0] < left[2] - 1 < right[2] - 1
            and min(left[3], right[3]) - max(left[1], right[1]) >= height / 2
        ):
            return True
    return False


def complete_caption_text(label, parts):
    """Replay the existing whole-caption grammar, never reconstruct an ID."""
    if not 1 <= len(parts) <= 32 or any(
        not isinstance(part, Mapping)
        or not isinstance(part.get("text"), str)
        or len(part["text"]) > 512
        for part in parts
    ):
        return ""
    raw = " ".join(part["text"] for part in parts)
    return identifier_width(raw).upper() if prefixed_label(raw) == label else ""


def ordered_caption_fragments(raw, observed, boxes, overlapping):
    """Every qualified literal is consumed once, in original physical order.

    Overlapping numeric detector pieces are not independent complete IDs. Other
    pieces, including series prefixes and letter suffixes, cannot disappear.
    Weak words do not become claims or reset the one-use cursor. The target is
    already read from original pixels; no digit/suffix joining publishes an ID.
    """
    selected = []
    for index, part in observed:
        text = part["text"]
        if (
            index in overlapping
            or prefixed_label(text)
            or _ROLE.fullmatch(text)
            or not any(char.isalnum() for char in text)
        ):
            continue
        x0, y0, x1, y1 = boxes[index]
        selected.append(
            {
                "text": identifier_width(text).strip().upper().removesuffix("."),
                "bbox": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            }
        )
    numeric = [part for part in selected if any(c.isnumeric() for c in part["text"])]
    for first, second in combinations((bounds(part) for part in numeric), 2):
        height = min(first[3] - first[1], second[3] - second[1])
        if min(first[3], second[3]) - max(first[1], second[1]) < height / 2:
            return False
    groups = group_text_lines(selected)
    if groups is None:
        return False
    cursor = 0
    for group in groups:
        for part in sorted(group, key=lambda item: bounds(item)[0]):
            position = raw.find(part["text"], cursor)
            if position < 0:
                return False
            cursor = position + len(part["text"])
    return True
