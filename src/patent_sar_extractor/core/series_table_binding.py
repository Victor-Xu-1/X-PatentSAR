"""Deterministic, fail-closed pairing for vertically labelled I-NNN tables.

This module has no PDF, model, configuration, or artifact-writing dependencies.
It returns evidence; the binder owns serialization and the final accuracy gate.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .printed_identifiers import identifier_key

_OCR_DUPLICATE_TOLERANCE = 2.0  # PDF points, anchored to the first observation.
_MAX_OUTSIDE_DISTANCE = 36.0
_MIN_TABLE_LABELS = 6


@dataclass(frozen=True)
class _Label:
    number: str
    y: float
    position: int
    raw_text: str


@dataclass(frozen=True)
class SeriesTableBinding:
    page_index: int
    source_label: str
    label: str
    structure: Mapping[str, Any]
    label_y: float
    center_distance: float
    evidence_position: int
    raw_source_label: str


@dataclass(frozen=True)
class SeriesTableResult:
    label_count: int
    bindings: tuple[SeriesTableBinding, ...]
    rejected_geometry: int = 0
    ambiguous_pairings: int = 0
    observed_keys: frozenset[str] = frozenset()
    recognized_pages: frozenset[int] = frozenset()
    unresolved_sources: tuple[tuple[int, str], ...] = ()

    @property
    def recognized(self) -> bool:
        return self.label_count >= _MIN_TABLE_LABELS


def _page_labels(lines: Sequence[tuple[float, str]], offset: int) -> list[_Label]:
    observations: list[tuple[float, str, str]] = []
    for raw_y, text in lines:
        try:
            y = float(raw_y)
        except (TypeError, ValueError, OverflowError):
            continue
        label = identifier_key(text, terminal_period=True)
        if math.isfinite(y) and y >= 0 and label.startswith("I-"):
            observations.append((y, label, text))
    labels: list[_Label] = []
    last_y: dict[str, float] = {}
    for y, number, raw_text in sorted(observations):
        if number in last_y and y - last_y[number] <= _OCR_DUPLICATE_TOLERANCE:
            continue
        last_y[number] = y
        labels.append(_Label(number, y, offset + len(labels), raw_text))
    return labels


def _geometry(structure: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    try:
        box = tuple(float(structure[key]) for key in ("x0", "y0", "x1", "y1"))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    x0, y0, x1, y1 = box
    if not all(math.isfinite(value) and value >= 0 for value in box):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _unique_best(edges: list[tuple[float, float, int]]) -> int | None:
    if not edges:
        return None
    ordered = sorted(edges)
    best = ordered[0]
    if len(ordered) > 1 and all(
        math.isclose(best[index], ordered[1][index], rel_tol=0, abs_tol=1e-6)
        for index in (0, 1)
    ):
        return None
    return best[2]


def _pair_page(
    page_index: int,
    structures: Sequence[Mapping[str, Any]],
    labels: Sequence[_Label],
) -> tuple[list[SeriesTableBinding], int, int]:
    valid: list[tuple[Mapping[str, Any], tuple[float, float, float, float]]] = []
    rejected = 0
    for structure in structures:
        box = _geometry(structure)
        if box is None:
            rejected += 1
        else:
            valid.append((structure, box))
    valid.sort(key=lambda item: (item[1][1], item[1][0]))
    by_structure: list[list[tuple[float, float, int]]] = [[] for _ in valid]
    by_label: list[list[tuple[float, float, int]]] = [[] for _ in labels]
    for structure_index, (_structure, (_x0, y0, _x1, y1)) in enumerate(valid):
        for label_index, label in enumerate(labels):
            outside = max(y0 - label.y, label.y - y1, 0.0)
            if outside <= _MAX_OUTSIDE_DISTANCE:
                center_distance = abs(label.y - (y0 + y1) / 2)
                by_structure[structure_index].append(
                    (outside, center_distance, label_index)
                )
                by_label[label_index].append(
                    (outside, center_distance, structure_index)
                )
    best_labels = [_unique_best(edges) for edges in by_structure]
    best_structures = [_unique_best(edges) for edges in by_label]
    ambiguous = sum(
        bool(edges) and best is None for edges, best in zip(by_structure, best_labels)
    )
    ambiguous += sum(
        bool(edges) and best is None for edges, best in zip(by_label, best_structures)
    )
    pairs: list[SeriesTableBinding] = []
    for structure_index, paired_label_index in enumerate(best_labels):
        # Mutual, unique nearest neighbours prevent arbitrary tie-breaking and
        # prevent a rejected/missing row from shifting the remaining matches.
        if (
            paired_label_index is None
            or best_structures[paired_label_index] != structure_index
        ):
            continue
        label = labels[paired_label_index]
        structure, (_x0, y0, _x1, y1) = valid[structure_index]
        pairs.append(
            SeriesTableBinding(
                page_index=page_index,
                source_label=label.number,
                label=label.number,
                structure=structure,
                label_y=label.y,
                center_distance=abs(label.y - (y0 + y1) / 2),
                evidence_position=label.position,
                raw_source_label=label.raw_text,
            )
        )
    return pairs, rejected, ambiguous


def _resolve_labels(
    pairs: Sequence[SeriesTableBinding],
    observed: Counter[str],
    active_keys: set[str] | None,
) -> tuple[SeriesTableBinding, ...]:
    ordered = sorted(pairs, key=lambda pair: pair.evidence_position)
    # Count all observed rows, including ones with no segmented structure.
    # An unpaired duplicate is still competing evidence, not permission to bind.
    return tuple(
        pair
        for pair in ordered
        if observed[pair.label] == 1
        and (active_keys is None or pair.label in active_keys)
    )


def pair_series_table(
    structures: Sequence[Mapping[str, Any]],
    page_indices: Sequence[int],
    lines_by_page: Mapping[int, Sequence[tuple[float, str]]],
    active_keys: set[str] | None,
) -> SeriesTableResult:
    """Pair rows without inventing absent activity IDs or resolving ambiguity.

    Preserve the entire printed I-series identifier. No missing integer,
    confusable I/1/l glyph or parent/suffix identity is inferred. Unresolved
    duplicates are withheld even when a plausible sequence is available.
    """
    by_page: dict[int, list[Mapping[str, Any]]] = {page: [] for page in page_indices}
    for structure in structures:
        try:
            page = int(structure.get("page_no", 0)) - 1
        except (TypeError, ValueError, OverflowError):
            continue
        if page in by_page:
            by_page[page].append(structure)
    observed: Counter[str] = Counter()
    candidates: list[SeriesTableBinding] = []
    label_count = rejected = ambiguous = 0
    observed_pages: set[int] = set()
    sources: list[tuple[int, str]] = []
    for page in sorted(by_page):
        labels = _page_labels(lines_by_page.get(page, ()), label_count)
        if labels:
            observed_pages.add(page)
        label_count += len(labels)
        observed.update(label.number for label in labels)
        sources.extend((page, label.number) for label in labels)
        pairs, invalid, uncertain = _pair_page(page, by_page[page], labels)
        candidates.extend(pairs)
        rejected += invalid
        ambiguous += uncertain
    bindings = (
        _resolve_labels(candidates, observed, active_keys)
        if label_count >= _MIN_TABLE_LABELS
        else ()
    )
    paired = {pair.label for pair in bindings}
    return SeriesTableResult(
        label_count,
        bindings,
        rejected,
        ambiguous,
        frozenset(str(number) for number in observed),
        frozenset(observed_pages) if label_count >= _MIN_TABLE_LABELS else frozenset(),
        tuple(
            dict.fromkeys(
                (page, label) for page, label in sources if label not in paired
            )
        )
        if label_count >= _MIN_TABLE_LABELS
        else (),
    )
