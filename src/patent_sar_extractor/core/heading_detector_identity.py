"""Original heading detector claims reuse the existing literal boundary guard."""

import re

from .cell_caption_fragments import truncated_caption_boundary
from .cell_ocr_line_groups import bounds
from .compound_caption import caption_identity, prefixed_label
from .ocr_claims import qualified_observation_runs
from .printed_identifiers import identifier_key
from .source_section_roles import (
    heading_members,
    nonfinal_original_label,
    section_heading,
)


def declaration_identity(value):
    return value["label_kind"], value["role"], heading_members(value)


def detector_conflicts(readings, declaration, *, whole_cell=None):
    members = heading_members(declaration)
    whole = prefixed_label(whole_cell) if whole_cell is not None else ""
    for reading in readings:
        parts = reading["detection_parts"]
        runs = qualified_observation_runs(parts)
        if runs is None:
            return True
        truncated = set()
        if len(members) == 1 and whole == members[0] and parts:
            observed = [(index, part) for run in runs for index, part in run]
            try:
                boxes = [bounds(part) for part in parts]
                for index, part in observed:
                    _label, end = caption_identity(part["text"])
                    if end == len(
                        re.sub(r"\s+", "", part["text"])
                    ) and truncated_caption_boundary(whole, index, observed, boxes):
                        truncated.add(index)
            except (ValueError, TypeError, IndexError, KeyError):
                return True
        for index, part in enumerate(parts):
            if part["confidence"] < 0.85 or index in truncated:
                continue
            observed = section_heading(part["text"])
            literal = identifier_key(part["text"], terminal_period=True)
            caption, end = caption_identity(part["text"])
            whole_text = whole_cell if whole_cell is not None else reading["raw_text"]
            compact = re.sub(r"\s+", "", part["text"]).casefold()
            if caption and (
                caption not in members
                or end < len(compact)
                and compact not in re.sub(r"\s+", "", whole_text).casefold()
            ):
                return True  # Retain full original ID and literal elution notes.
            if (
                observed
                and declaration_identity(observed) != declaration_identity(declaration)
                or literal
                and literal not in members
                or not observed
                and nonfinal_original_label(part["text"])
            ):
                return True
    return False
