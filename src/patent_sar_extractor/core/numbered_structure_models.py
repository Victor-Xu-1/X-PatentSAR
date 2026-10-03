"""Typed original numbered cells, primary assignments and proved reprint sources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

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
        }


@dataclass(frozen=True)
class NumberedTableIssue:
    page_index: int
    label: str
    reason: str


@dataclass(frozen=True)
class NumberedTableResult:
    recognized_pages: tuple[int, ...]
    observed_keys: frozenset[str]
    bindings: tuple[NumberedTableBinding, ...]
    issues: tuple[NumberedTableIssue, ...]

    reprints: tuple[NumberedTableBinding, ...] = ()

    @property
    def recognized(self) -> bool:
        return bool(self.recognized_pages)
