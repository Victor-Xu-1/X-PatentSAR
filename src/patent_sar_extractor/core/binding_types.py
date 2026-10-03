"""Typed binding inputs and configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


@dataclass
class BinderConfig:
    """绑定算法配置"""

    search_below_pixels: int = 300
    search_above_pixels: int = 200
    search_side_pixels: int = 300
    cluster_y_threshold: int = 50


SourceKind = Literal["numbered_cell", "exact_caption", "legacy_table"]


@dataclass(frozen=True)
class BindingCandidate:
    label_key: str
    structure_id: str
    page_index: int
    source: SourceKind
    binding: Mapping[str, Any]


@dataclass(frozen=True)
class BindingConflict:
    label_key: str
    page_index: int
    reason: str


@dataclass(frozen=True)
class SourceOwnership:
    page_indices: frozenset[int]
    structure_ids: frozenset[str]
    label_keys: frozenset[str]

    def protects(self, label_key: str, structure_id: str, page_index: int) -> bool:
        return (
            label_key in self.label_keys
            or structure_id in self.structure_ids
            or page_index in self.page_indices
        )


@dataclass(frozen=True)
class BindingObservations:
    page_indices: list[int]
    pages_text: dict[int, str]
    line_map: dict[int, list[tuple[float, str]]]
    authoritative_table_pages: frozenset[int]
    workers: int


@dataclass
class BindingSelection:
    bindings: list[dict[str, Any]]
    blocks: list[dict[str, Any]]
    detected_style: str
    no_binding: list[str]
    unbound_pages: list[dict[str, Any]]
    visible_label_cache: dict[str, dict[str, Any]]
    visual_grid_bindings: list[dict[str, Any]]
