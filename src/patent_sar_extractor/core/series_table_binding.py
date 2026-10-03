"""Deterministic, fail-closed pairing for vertically labelled I-NNN tables.

This module has no PDF, model, configuration, or artifact-writing dependencies.
It returns evidence; the binder owns serialization and the final accuracy gate.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:I|1|l)\s*[-\u2013\u2014]\s*([1-9]\d{0,4})(?!\d)",
    re.IGNORECASE,
)
_OCR_DUPLICATE_TOLERANCE = 2.0  # PDF points, anchored to the first observation.
_MAX_OUTSIDE_DISTANCE = 36.0
_MIN_TABLE_LABELS = 6


@dataclass(frozen=True)
class _Label:
    number: int
    y: float
    position: int


@dataclass(frozen=True)
class SeriesTableBinding:
    page_index: int
    source_label: int
    label: int
    structure: Mapping[str, Any]
    label_y: float
    center_distance: float
    evidence_position: int
    correction_reason: str = ""


@dataclass(frozen=True)
class SeriesTableResult:
    label_count: int
    bindings: tuple[SeriesTableBinding, ...]
    rejected_geometry: int = 0
    ambiguous_pairings: int = 0
    observed_keys: frozenset[str] = frozenset()
    recognized_pages: frozenset[int] = frozenset()

    @property
    def recognized(self) -> bool:
        return self.label_count >= _MIN_TABLE_LABELS


def _page_labels(lines: Sequence[tuple[float, str]], offset: int) -> list[_Label]:
    observations: list[tuple[float, int]] = []
    for raw_y, text in lines:
        try:
            y = float(raw_y)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(y) and y >= 0:
            observations.extend(
                (y, int(match.group(1))) for match in _LABEL_RE.finditer(text)
            )
    labels: list[_Label] = []
    last_y: dict[int, float] = {}
    for y, number in sorted(observations):
        if number in last_y and y - last_y[number] <= _OCR_DUPLICATE_TOLERANCE:
            continue
        last_y[number] = y
        labels.append(_Label(number, y, offset + len(labels)))
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
            )
        )
    return pairs, rejected, ambiguous


def _resolve_labels(
    pairs: Sequence[SeriesTableBinding],
    observed: Counter[int],
    active_keys: set[str],
) -> tuple[SeriesTableBinding, ...]:
    ordered = sorted(pairs, key=lambda pair: pair.evidence_position)
    proposals: dict[int, int] = {}
    for index in range(1, len(ordered) - 1):
        previous, current, following = ordered[index - 1 : index + 2]
        expected = previous.source_label + 1
        if (
            observed[current.source_label] > 1
            and observed[previous.source_label] == observed[following.source_label] == 1
            and previous.evidence_position + 1 == current.evidence_position
            and current.evidence_position + 1 == following.evidence_position
            and current.page_index - previous.page_index in (0, 1)
            and following.page_index - current.page_index in (0, 1)
            and following.source_label == expected + 1
            and expected not in observed
            and str(expected) in active_keys
        ):
            proposals[index] = expected
    proposal_counts = Counter(proposals.values())
    remaining = observed.copy()
    resolved: list[SeriesTableBinding] = []
    for index, current in enumerate(ordered):
        proposed = proposals.get(index)
        if proposed is not None and proposal_counts[proposed] == 1:
            previous, following = ordered[index - 1], ordered[index + 1]
            reason = (
                f"Source label I-{current.source_label} is duplicated and out of sequence "
                f"between I-{previous.source_label} and I-{following.source_label}; "
                f"resolved as I-{proposed}."
            )
            remaining[current.source_label] -= 1
            remaining[proposed] += 1
            current = replace(current, label=proposed, correction_reason=reason)
        resolved.append(current)
    # Count all observed rows, including ones with no segmented structure.
    # An unpaired duplicate is still competing evidence, not permission to bind.
    return tuple(
        pair
        for pair in resolved
        if remaining[pair.label] == 1 and str(pair.label) in active_keys
    )


def pair_series_table(
    structures: Sequence[Mapping[str, Any]],
    page_indices: Sequence[int],
    lines_by_page: Mapping[int, Sequence[tuple[float, str]]],
    active_keys: set[str],
) -> SeriesTableResult:
    """Pair rows without inventing absent activity IDs or resolving ambiguity.

    Source-print corrections require a repeated printed ID, unique adjacent
    anchors proving a single missing integer, and that integer in the activity
    set but nowhere in the observed table. Anchors cannot bridge an unobserved
    page. Unresolved duplicates are withheld.
    """
    by_page: dict[int, list[Mapping[str, Any]]] = {page: [] for page in page_indices}
    for structure in structures:
        try:
            page = int(structure.get("page_no", 0)) - 1
        except (TypeError, ValueError, OverflowError):
            continue
        if page in by_page:
            by_page[page].append(structure)
    observed: Counter[int] = Counter()
    candidates: list[SeriesTableBinding] = []
    label_count = rejected = ambiguous = 0
    observed_pages: set[int] = set()
    for page in sorted(by_page):
        labels = _page_labels(lines_by_page.get(page, ()), label_count)
        if labels:
            observed_pages.add(page)
        label_count += len(labels)
        observed.update(label.number for label in labels)
        pairs, invalid, uncertain = _pair_page(page, by_page[page], labels)
        candidates.extend(pairs)
        rejected += invalid
        ambiguous += uncertain
    bindings = (
        _resolve_labels(candidates, observed, active_keys)
        if label_count >= _MIN_TABLE_LABELS
        else ()
    )
    return SeriesTableResult(label_count, bindings, rejected, ambiguous,
        frozenset(str(number) for number in observed),
        frozenset(observed_pages) if label_count >= _MIN_TABLE_LABELS else frozenset(),
    )
