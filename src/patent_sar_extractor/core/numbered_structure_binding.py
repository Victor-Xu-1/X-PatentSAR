"""Original-cell ownership for numbered, ruled compound/structure tables.

Grid detection and cell OCR are shared with activity extraction. This module
neither reconstructs a global sequence nor fills missing/letter-suffixed IDs.
Recognized table pages remain protected even when none of their cells bind.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from itertools import pairwise
from typing import Any, Protocol

from .numbered_structure_models import (
    Box,
    NumberedTableBinding,
    NumberedTableCell,
    NumberedTableIssue,
    NumberedTableResult,
)
from .numbered_structure_pairs import (
    pair_numbered_table_cells,
    valid_cell_binding_evidence,
)
from .structure_catalogs import (
    Catalog,
    catalog_at,
    catalog_marks,
)

_HEADER_RE = re.compile(
    r"(?:Cmpd|Cpd|Compound|Example)\.?\s*(?:No\.?|ID|#)", re.IGNORECASE
)

__all__ = [
    "NumberedTableBinding",
    "NumberedTableCell",
    "NumberedTableIssue",
    "NumberedTableResult",
    "bind_numbered_tables",
    "pair_numbered_table_cells",
    "valid_cell_binding_evidence",
]


class _CellReading(Protocol):
    value: str
    observations: list[dict[str, Any]]
    needs_review: bool


def _cell_text(tokens: Sequence[Mapping[str, Any]], bounds: Box) -> str:
    return " ".join(
        str(t.get("text", ""))
        for t in tokens
        if bounds[0] < float(t["x"]) < bounds[2]
        and bounds[1] < float(t["y"]) < bounds[3]
    )


def _grid_axes(grid: Mapping[str, Any]) -> tuple[list[float], list[float]] | None:
    try:
        xs, ys = [float(v) for v in grid["xs"]], [float(v) for v in grid["ys"]]
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if len(xs) not in (3, 5) or len(ys) < 3:
        return None
    if any(not math.isfinite(v) or v < 0 for v in [*xs, *ys]) or any(
        b <= a for axis in (xs, ys) for a, b in pairwise(axis)
    ):
        return None
    if any(
        xs[i + 1] - xs[i] > (xs[i + 2] - xs[i + 1]) * 0.65
        for i in range(0, len(xs) - 1, 2)
    ):
        return None
    return xs, ys


def bind_numbered_tables(
    doc: Any,
    structures: Sequence[Mapping[str, Any]],
    page_indices: Sequence[int],
    active_keys: set[str] | None = None,
    *,
    grids_for_page: Callable[[Any], Sequence[Mapping[str, Any]]] | None = None,
    tokens_for_page: Callable[[Any], list[dict[str, Any]]] | None = None,
    cell_reader: Callable[[Any, Box, list[dict[str, Any]], str, bool], _CellReading]
    | None = None,
) -> NumberedTableResult:
    """Observe only proven candidate grids; adjacent continuation geometry carries.

    The original document is caller-owned. No PDF, crop, cache or result artifact
    is rewritten here. Fresh coordinate OCR is restricted to detected grids.
    """
    if not page_indices or (active_keys is not None and not active_keys):
        return NumberedTableResult((), frozenset(), (), ())
    if grids_for_page is None or tokens_for_page is None:
        from .table_geometry import detect_ruled_table_regions, page_tokens

        grids_for_page = grids_for_page or detect_ruled_table_regions
        tokens_for_page = tokens_for_page or page_tokens
    if cell_reader is None:
        from .table_cells import read_cell

        cell_reader = read_cell
    cells = []
    recognized: set[int] = set()
    carry: tuple[int, list[float]] | None = None
    prior_catalog = Catalog()
    for page_index in sorted(set(page_indices)):
        if not 0 <= page_index < len(doc):
            continue
        page = doc[page_index]
        grids: list[tuple[list[float], list[float]]] = []
        for grid in grids_for_page(page):
            axes = _grid_axes(grid)
            if axes is not None:
                grids.append(axes)
        if not grids:
            continue
        tokens = tokens_for_page(page)
        marks = catalog_marks(tokens)
        native = bool(page.get_text("words"))
        for grid_index, (xs, ys) in enumerate(
            sorted(grids, key=lambda axes: axes[1][0])
        ):
            pairs = (len(xs) - 1) // 2
            headers = []
            for pair in range(pairs):
                start = pair * 2
                left = _cell_text(tokens, (xs[start], ys[0], xs[start + 1], ys[1]))
                right = _cell_text(tokens, (xs[start + 1], ys[0], xs[start + 2], ys[1]))
                headers.append(
                    bool(
                        _HEADER_RE.search(left)
                        and re.search(r"\bStructure\b", right, re.IGNORECASE)
                    )
                )
            has_header = all(headers)
            continuation = bool(
                carry
                and carry[0] + 1 == page_index
                and ys[0] < 130
                and len(carry[1]) == len(xs)
                and all(abs(a - b) <= 4 for a, b in zip(carry[1], xs))
            )
            if not has_header and not continuation:
                continue
            first_row = 1 if has_header else 0
            catalog = catalog_at(marks, ys[0], prior_catalog)
            # The existing I-series module owns labels with a series prefix.
            if any(
                re.fullmatch(
                    r"(?:I|l)\s*[-–—]\s*[1-9]\d*",
                    _cell_text(tokens, (xs[0], ys[r], xs[1], ys[r + 1])).strip(),
                    re.IGNORECASE,
                )
                for r in range(first_row, len(ys) - 1)
            ):
                continue
            recognized.add(page_index)
            carry = page_index, xs
            for row in range(first_row, len(ys) - 1):
                for pair in range(pairs):
                    start = pair * 2
                    label_bounds = (xs[start], ys[row], xs[start + 1], ys[row + 1])
                    reading = cell_reader(page, label_bounds, tokens, "id", native)
                    cells.append(
                        NumberedTableCell(
                            page_index,
                            grid_index,
                            row,
                            pair,
                            str(reading.value),
                            label_bounds,
                            (xs[start + 1], ys[row], xs[start + 2], ys[row + 1]),
                            tuple(dict(o) for o in reading.observations),
                            not reading.needs_review,
                            catalog,
                        )
                    )
        if marks:
            prior_catalog = marks[-1][1]
    return pair_numbered_table_cells(
        cells, structures, active_keys, recognized_pages=recognized
    )
