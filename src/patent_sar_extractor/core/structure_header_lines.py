"""Bounded original multiline header groups; pixel readers still prove roles."""

from itertools import pairwise

from .activity_context_geometry import MAX_TABLES
from .printed_identifiers import identifier_key
from .source_cell_tokens import cell_lines
from .source_section_roles import section_heading
from .source_table_markers import TABLE_CAPTION_START
from .structure_table_headers import (
    header_groups,
    structure_column_pairs,
    structure_header_role,
)

MAX_HEADER_LINES = 8
MAX_COLUMNS = 64


def _body_or_boundary(groups):
    texts = [g["text"] for g in groups]
    text = " ".join(texts)
    return (
        not any(structure_header_role(t) for t in texts)
        and any(identifier_key(t, wrapped=True, terminal_period=True) for t in texts)
    ) or (
        not structure_column_pairs(texts)
        and (TABLE_CAPTION_START.match(text) or section_heading(text))
    )


def _join_columns(columns, following):
    """Each original group has one overlapping column or a new disjoint slot."""
    assigned, additions = {}, []
    for group in following:
        owners = [
            i
            for i, old in enumerate(columns)
            if min(old["bbox"][2], group["bbox"][2])
            > max(old["bbox"][0], group["bbox"][0])
        ]
        if len(owners) > 1 or owners and owners[0] in assigned:
            return None
        if owners:
            assigned[owners[0]] = group
        else:
            additions.append(group)
    result = []
    for i, old in enumerate(columns):
        next_part = assigned.get(i)
        if next_part is None:
            result.append(old)
            continue
        a, b = old["bbox"], next_part["bbox"]
        result.append(
            {
                "text": old["text"] + "\n" + next_part["text"],
                "bbox": [
                    min(a[0], b[0]),
                    min(a[1], b[1]),
                    max(a[2], b[2]),
                    max(a[3], b[3]),
                ],
            }
        )
    result = sorted([*result, *additions], key=lambda g: g["bbox"][0])
    return (
        result
        if len(result) <= MAX_COLUMNS
        and all(a["bbox"][2] < b["bbox"][0] for a, b in pairwise(result))
        else None
    )


def _adjacent(previous, following):
    return (
        min(g["bbox"][1] for g in following) - max(g["bbox"][3] for g in previous) <= 18
    )


def original_header_groups(tokens, bounds):
    """Nomination only: full original windows are independently read afterwards.

    A connected longer block conserves every original word, even when its role
    is unknown; a valid shorter suffix cannot silently discard that prefix.
    Actual identifier rows and original section/table boundaries stop wrapping.
    """
    lines = [header_groups(line) for line in cell_lines(tokens, bounds)]
    blocks = []
    for start, seed in enumerate(lines):
        if not seed or len(seed) > MAX_COLUMNS or _body_or_boundary(seed):
            continue
        columns, end = seed, start + 1
        cue = any(structure_header_role(g["text"]) for g in seed)
        while end < min(len(lines), start + MAX_HEADER_LINES):
            following = lines[end]
            if (
                not following
                or not _adjacent(lines[end - 1], following)
                or _body_or_boundary(following)
            ):
                break
            joined = _join_columns(columns, following)
            if joined is None:
                break
            columns, end = joined, end + 1
            cue |= any(structure_header_role(g["text"]) for g in following)
        if cue:
            if (
                end == start + MAX_HEADER_LINES
                and end < len(lines)
                and lines[end]
                and _adjacent(lines[end - 1], lines[end])
                and not _body_or_boundary(lines[end])
                and _join_columns(columns, lines[end]) is not None
            ):
                raise ValueError("Original multiline header exceeds its line bound")
            if len(blocks) >= MAX_TABLES:
                raise ValueError(
                    "Original header candidate inventory exceeds its bound"
                )
            blocks.append((start, end, columns))
    # Maximal original line intervals, not a confidence vote or nearest header.
    output, last_end = [], -1
    for _start, end, groups in sorted(blocks, key=lambda b: (b[0], -b[1])):
        if end <= last_end:
            continue
        last_end = end
        if structure_column_pairs([g["text"] for g in groups]):
            output.append(groups)
    return output
