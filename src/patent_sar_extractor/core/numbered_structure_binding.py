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
    _box,
    _overlaps,
    pair_numbered_table_cells,
    valid_cell_binding_evidence,
)
from .structure_catalogs import (
    Catalog,
    catalog_at,
    catalog_marks,
)
from .structure_table_headers import structure_column_pairs

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
    if not 3 <= len(xs) <= 65 or len(ys) < 3:
        return None
    if any(not math.isfinite(v) or v < 0 for v in [*xs, *ys]) or any(
        b <= a for axis in (xs, ys) for a, b in pairwise(axis)
    ):
        return None
    return xs, ys


def _unused_pair(
    page: Any,
    label_bounds: Box,
    structure_bounds: Box,
    structures: Sequence[Mapping[str, Any]],
    page_index: int,
) -> bool:
    """Both original cells must be blank, with no rival segment evidence."""
    if not callable(getattr(page, "get_pixmap", None)):
        return False  # Absence of pixel evidence cannot prove an unused cell.
    for structure in structures:
        if structure.get("page_no") != page_index + 1:
            continue
        box = _box([structure.get(key) for key in ("x0", "y0", "x1", "y1")])
        if box is None or _overlaps(box, structure_bounds):
            return False
    from .table_cells import cell_image

    for bounds in (label_bounds, structure_bounds):
        image = cell_image(page, bounds, 150)
        # A fixed tiny noise allowance cannot erase a small labelled molecule
        # merely because its cell is large. Grid rules are excluded by cell_image.
        if int((image.min(axis=2) < 200).sum()) > 4:
            return False
    return True


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
    carry: tuple[int, list[float], list[str], tuple[tuple[int, int], ...]] | None = None
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
            headers = [
                _cell_text(tokens, (xs[column], ys[0], xs[column + 1], ys[1]))
                for column in range(len(xs) - 1)
            ]
            pairs = structure_column_pairs(headers)
            has_header = bool(pairs)
            continuation = bool(
                carry
                and carry[0] + 1 == page_index
                and ys[0] < 130
                and len(carry[1]) == len(xs)
                and all(abs(a - b) <= 4 for a, b in zip(carry[1], xs))
            )
            if not has_header and not continuation:
                continue
            if not has_header and carry:
                headers, pairs = carry[2], carry[3]
            first_row = 1 if has_header else 0
            catalog = catalog_at(marks, ys[0], prior_catalog)
            # The existing I-series module owns labels with a series prefix.
            if any(
                re.fullmatch(
                    r"(?:I|l)\s*[-–—]\s*[1-9]\d*",
                    _cell_text(
                        tokens, (xs[column], ys[r], xs[column + 1], ys[r + 1])
                    ).strip(),
                    re.IGNORECASE,
                )
                for r in range(first_row, len(ys) - 1)
                for column, _ in pairs
            ):
                continue
            recognized.add(page_index)
            carry = page_index, xs, headers, pairs
            for row in range(first_row, len(ys) - 1):
                for pair, (identifier, structure) in enumerate(pairs):
                    label_bounds = (
                        xs[identifier],
                        ys[row],
                        xs[identifier + 1],
                        ys[row + 1],
                    )
                    structure_bounds = (
                        xs[structure],
                        ys[row],
                        xs[structure + 1],
                        ys[row + 1],
                    )
                    if not _cell_text(tokens, label_bounds).strip() and _unused_pair(
                        page, label_bounds, structure_bounds, structures, page_index
                    ):
                        continue
                    reading = cell_reader(page, label_bounds, tokens, "id", native)
                    cells.append(
                        NumberedTableCell(
                            page_index,
                            grid_index,
                            row,
                            pair,
                            str(reading.value),
                            label_bounds,
                            structure_bounds,
                            tuple(dict(o) for o in reading.observations),
                            not reading.needs_review,
                            catalog,
                            {
                                "grid_xs": xs,
                                "headers": headers,
                                "identifier_column": identifier,
                                "structure_column": structure,
                            },
                        )
                    )
        if marks:
            prior_catalog = marks[-1][1]
    return pair_numbered_table_cells(
        cells, structures, active_keys, recognized_pages=recognized
    )
