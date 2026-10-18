"""One original-source owner for numbered ruled/unruled structure tables.

Source discovery precedes all numbered-cell construction. Actual physical and
logical regions share source roles, one pair matcher and the existing writer.
No PDF, crop, cache or scientific result is rewritten by this coordinator.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from .binding_progress import BindingObserver
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
from .structure_column_cells import observe_ruled_cells
from .unruled_structure_observation import observe_unruled_tables

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
    page_texts: Mapping[int, str] | None = None,
    caption_roles: Mapping | None = None,
    caption_frames: Mapping | None = None,
    progress: BindingObserver | None = None,
) -> NumberedTableResult:
    """Register original frames/roles, then build cells for the single matcher."""
    if not page_indices or (active_keys is not None and not active_keys):
        return NumberedTableResult((), frozenset(), (), ())
    if grids_for_page is None or tokens_for_page is None:
        from .table_geometry import detect_ruled_table_regions, page_tokens

        grids_for_page = grids_for_page or detect_ruled_table_regions
        tokens_for_page = tokens_for_page or page_tokens
    if cell_reader is None:
        from .table_cells import read_cell

        cell_reader = read_cell
    read_tokens, source_tokens = tokens_for_page, {}

    def shared_tokens(page):
        if page.number not in source_tokens:
            source_tokens[page.number] = read_tokens(page)
        return source_tokens[page.number]

    unruled, sections, issues, protected, pages, keys = observe_unruled_tables(
        doc,
        structures,
        page_indices,
        grids_for_page,
        shared_tokens,
        page_texts=page_texts,
        caption_roles=caption_roles,
        caption_frames=caption_frames,
        progress=progress,
    )
    cells, cell_issues = observe_ruled_cells(
        doc, structures, sections, shared_tokens, cell_reader, progress=progress
    )
    ruled = pair_numbered_table_cells(
        cells, structures, active_keys, recognized_pages=pages
    )
    return NumberedTableResult(
        tuple(sorted(pages)),
        ruled.observed_keys | frozenset(keys),
        (
            *ruled.bindings,
            *(b for b in unruled if active_keys is None or b.label in active_keys),
        ),
        (*ruled.issues, *cell_issues, *issues),
        ruled.reprints,
        tuple(sections),
        frozenset(protected),
        frozenset(
            pages
            - {
                section["page_no"] - 1
                for section in sections
                if section["role"]
                in {"structure_column_anchor", "unruled_structure_region"}
            }
        ),
    )
