"""Typed original numbered cells, primary assignments and proved reprint sources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .structure_catalogs import Catalog

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class NumberedTableCell:
    page_index: int
    grid_index: int
    row: int
    pair: int
    label: str
    label_bounds: Box
    structure_bounds: Box
    observations: tuple[Mapping[str, Any], ...]
    label_confirmed: bool
    catalog: Catalog = field(default_factory=Catalog)
    column_ownership: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class NumberedTableBinding:
    label: str
    structure: Mapping[str, Any]
    cell: NumberedTableCell

    def evidence(self) -> dict[str, Any]:
        return {
            "coordinate_space": "original_pdf_points",
            "page_no": self.cell.page_index + 1,
            "grid": self.cell.grid_index,
            "row": self.cell.row,
            "pair": self.cell.pair,
            "source_label": self.label,
            "source_catalog": self.cell.catalog.identifier,
            "source_catalog_title": self.cell.catalog.title,
            "label_bbox": list(self.cell.label_bounds),
            "structure_cell_bbox": list(self.cell.structure_bounds),
            "segment_bbox": [self.structure[k] for k in ("x0", "y0", "x1", "y1")],
            "structure_id": self.structure["id"],
            "contained_segment_count": 1,
            "observed_label_count": 1,
            "observations": [dict(o) for o in self.cell.observations],
            **(
                {"column_ownership": dict(self.cell.column_ownership)}
                if self.cell.column_ownership
                else {}
            ),
        }


@dataclass(frozen=True)
class NumberedTableIssue:
    page_index: int
    label: str
    reason: str
    evidence: Mapping[str, Any] = field(default_factory=dict, hash=False)


class OriginalTableBinding(Protocol):
    label: str
    structure: Mapping[str, Any]

    def evidence(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class NumberedTableResult:
    recognized_pages: tuple[int, ...]
    observed_keys: frozenset[str]
    bindings: tuple[OriginalTableBinding, ...]
    issues: tuple[NumberedTableIssue, ...]

    reprints: tuple[NumberedTableBinding, ...] = ()
    source_sections: tuple[dict, ...] = ()
    protected_structure_ids: frozenset[str] = frozenset()
    reserved_pages: frozenset[int] | None = None

    @property
    def ownership_pages(self):
        return (
            frozenset(self.recognized_pages)
            if self.reserved_pages is None
            else self.reserved_pages
        )

    @property
    def recognized(self) -> bool:
        return bool(self.recognized_pages)
