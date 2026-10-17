"""Bounded original-row nomination; text never supplies structure ownership."""

import re
from bisect import bisect_right

from .activity_context_geometry import grid_box, validate_grid_axes
from .activity_identity import is_id_header
from .printed_identifiers import LABEL_PREFIX, identifier_key
from .source_cell_tokens import cell_text, grid_token_index
from .structure_table_headers import structure_column_pairs
from .table_cells import prefixed_label


def _bounded_axes(region, tokens, boxes=()):
    xs, ys = region["xs"], region["ys"]
    validate_grid_axes({"xs": xs, "ys": ys}, grid_box(region))
    if (
        (len(xs) - 1) * (len(ys) - 1) > 25000
        or len(tokens) > 50000
        or len(boxes) > 25000
    ):
        raise ValueError("Original caption grid exceeds its resource bound")
    return xs, ys


def numbered_header_nominee(region, tokens):
    """Defer literal ID/structure headers to the existing independent reader.

    This nominates a reader, not ownership or successful empty data. Invalid or
    conflicting source headers still remain unresolved in that same reader.
    """
    xs, ys = _bounded_axes(region, tokens)
    selected = grid_token_index(tokens, xs, ys)
    return bool(
        structure_column_pairs(
            [
                cell_text(
                    selected.get((0, col), []), (xs[col], ys[0], xs[col + 1], ys[1])
                )
                for col in range(len(xs) - 1)
            ]
        )
    )


def inside(box, cell):
    return bool(
        box
        and cell[0] - 2 <= box[0] < box[2] <= cell[2] + 2
        and cell[1] - 2 <= box[1] < box[3] <= cell[3] + 2
    )


def caption_rows(region, tokens, boxes, role):
    xs, ys = _bounded_axes(region, tokens, boxes)
    selected, drawings = grid_token_index(tokens, xs, ys), set()
    for box in boxes:
        if box is None:
            continue
        col = bisect_right(xs, (box[0] + box[2]) / 2) - 1
        row = bisect_right(ys, (box[1] + box[3]) / 2) - 1
        for r in range(max(0, row - 1), min(len(ys) - 1, row + 2)):
            for c in range(max(0, col - 1), min(len(xs) - 1, col + 2)):
                if inside(box, (xs[c], ys[r], xs[c + 1], ys[r + 1])):
                    drawings.add((r, c))
    rows, kinds = [], []
    for row in range(len(ys) - 1):
        labels, drawing = [], False
        for col in range(len(xs) - 1):
            cell = (xs[col], ys[row], xs[col + 1], ys[row + 1])
            raw = cell_text(selected.get((row, col), []), cell)
            label = prefixed_label(raw)
            short = ys[row + 1] - ys[row] <= 45
            bare = short and bool(identifier_key(raw))
            unresolved = bool(
                short
                and raw.strip()
                and role
                and role.get("table_key")
                and not is_id_header(raw)
            )
            prefixed = short and bool(re.match(LABEL_PREFIX, raw, re.IGNORECASE))
            if label or prefixed or bare or unresolved:
                labels.append(
                    (
                        col,
                        label or identifier_key(raw),
                        cell,
                        bare
                        or unresolved
                        and role.get("role") == "compound"
                        and not prefixed
                        and not label,
                    )
                )
            drawing |= (row, col) in drawings
        rows.append(labels)
        kinds.append(
            "label"
            if labels and not drawing
            else "drawing"
            if drawing and not labels
            else "unknown"
        )
    return rows, kinds
