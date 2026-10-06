"""Single exact numbered-cell matcher, including verified selected reprints."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .numbered_structure_models import (
    Box,
    NumberedTableBinding,
    NumberedTableCell,
    NumberedTableIssue,
    NumberedTableResult,
)
from .structure_catalogs import repeated_selected_catalogs

_ID_RE = re.compile(r"[1-9]\d{0,3}[A-Z]?\.?", re.IGNORECASE)


def _label(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    return text.removesuffix(".").upper() if _ID_RE.fullmatch(text) else ""


def _box(value: Any) -> Box | None:
    if not isinstance(value, (list, tuple)) or any(isinstance(v, bool) for v in value):
        return None
    try:
        if len(value) != 4:
            return None
        box = tuple(float(v) for v in value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(v) and v >= 0 for v in box):
        return None
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box[0], box[1], box[2], box[3]


def _inside(inner: Box, outer: Box) -> bool:
    return (
        outer[0] <= inner[0] < inner[2] <= outer[2]
        and outer[1] <= inner[1] < inner[3] <= outer[3]
    )


def _overlaps(a: Box, b: Box) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _adjacent_cells(label_box: Box | None, structure_box: Box | None) -> bool:
    return bool(
        label_box
        and structure_box
        and all(
            math.isclose(label_box[i], structure_box[i], abs_tol=0.01) for i in (1, 3)
        )
        and math.isclose(label_box[2], structure_box[0], abs_tol=0.01)
    )


def _confirmed_observations(
    label: str, observations: Sequence[Mapping[str, Any]]
) -> bool:
    methods: set[str] = set()
    for observation in observations:
        if (
            not isinstance(observation, Mapping)
            or _label(observation.get("text")) != label
        ):
            continue
        method = str(observation.get("method") or "")
        if method == "native_cell":
            return True
        if method.startswith("cell_ocr_"):
            if isinstance(observation.get("confidence"), bool):
                continue
            try:
                score = float(observation.get("confidence", 0))
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(score) or not 0.85 <= score <= 1:
                continue
        methods.add(method)
    return "cell_ocr_400dpi" in methods and bool(
        methods & {"page_ocr_cell", "cell_ocr_600dpi"}
    )


def valid_cell_binding_evidence(binding: Mapping[str, Any]) -> bool:
    """Recheck the serialized proof before the shared strict accuracy gate."""
    evidence = binding.get("numbered_table_cell_evidence")
    if not isinstance(evidence, Mapping):
        return False
    source = _label(evidence.get("source_label"))
    target = re.sub(
        r"^(?:Compound|Cpd|Example)\s+",
        "",
        str(binding.get("compound_id") or binding.get("cpd") or ""),
        flags=re.IGNORECASE,
    )
    try:
        if isinstance(binding.get("page_no"), bool) or not isinstance(
            binding.get("page_no"), int
        ):
            return False
        if any(
            type(evidence.get(key)) is not int
            for key in ("page_no", "contained_segment_count", "observed_label_count")
        ):
            return False
        page_no = int(binding.get("page_no", 0))
        segment = _box(
            [
                binding.get(k)
                for k in ("struct_x0", "struct_y0", "struct_x1", "struct_y1")
            ]
        )
        label_box = _box(evidence.get("label_bbox"))
        cell_box = _box(evidence.get("structure_cell_bbox"))
        source_box = _box(evidence.get("segment_bbox"))
        observations = evidence.get("observations")
        return bool(
            source
            and _label(target) == source
            and evidence.get("coordinate_space") == "original_pdf_points"
            and page_no > 0
            and evidence.get("page_no") == page_no
            and evidence.get("contained_segment_count") == 1
            and evidence.get("observed_label_count") == 1
            and bool(binding.get("structure_id"))
            and evidence.get("structure_id") == binding.get("structure_id")
            and _adjacent_cells(label_box, cell_box)
            and segment
            and cell_box
            and source_box == segment
            and _inside(segment, cell_box)
            and isinstance(observations, (list, tuple))
            and 1 <= len(observations) <= 3
            and _confirmed_observations(source, observations)
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _pair_cells(
    cells: Sequence[NumberedTableCell],
    structures: Sequence[Mapping[str, Any]],
    active_keys: set[str] | None,
    *,
    recognized_pages: Sequence[int] | set[int] = (),
    repeatable_labels: frozenset[str] = frozenset(),
) -> NumberedTableResult:
    """Require one printed ID and one complete segment in its adjacent cell."""
    observed = Counter(_label(cell.label) for cell in cells if _label(cell.label))
    observed_keys = set(observed)
    for cell in cells:
        if cell.label_confirmed:
            continue
        observed_keys.update(
            _label(o.get("text")) for o in cell.observations if _label(o.get("text"))
        )
    structure_ids = Counter(str(s.get("id") or "") for s in structures)
    by_page: dict[int, list[tuple[Mapping[str, Any], Box | None]]] = {}
    for segment in structures:
        try:
            page = int(segment.get("page_no", 0)) - 1
        except (TypeError, ValueError, OverflowError):
            continue
        by_page.setdefault(page, []).append(
            (segment, _box([segment.get(k) for k in ("x0", "y0", "x1", "y1")]))
        )
    bindings = []
    issues = []
    for cell in sorted(
        cells, key=lambda c: (c.page_index, c.grid_index, c.row, c.pair)
    ):
        label = _label(cell.label)
        label_box, cell_box = _box(cell.label_bounds), _box(cell.structure_bounds)
        reason = ""
        if (
            not label
            or not cell.label_confirmed
            or not _confirmed_observations(label, cell.observations)
        ):
            reason = "unresolved_label"
        elif observed[label] != 1 and label not in repeatable_labels:
            reason = "duplicate_label"
        elif not _adjacent_cells(label_box, cell_box):
            reason = "invalid_cell_geometry"
        if reason:
            issues.append(NumberedTableIssue(cell.page_index, label, reason))
            continue
        if active_keys is not None and label not in active_keys:
            continue
        if any(box is None for _segment, box in by_page.get(cell.page_index, [])):
            # An unlocatable segment is competing evidence on this page, not
            # proof that the one valid box is the only molecule in the cell.
            issues.append(
                NumberedTableIssue(cell.page_index, label, "invalid_segment_geometry")
            )
            continue
        contained = []
        crossing = False
        for segment, box in by_page.get(cell.page_index, []):
            if box and cell_box and _inside(box, cell_box):
                contained.append(segment)
            elif box and cell_box and _overlaps(box, cell_box):
                crossing = True
        if crossing:
            reason = "boundary_crossing_segment"
        elif not contained:
            reason = "missing_segment"
        elif len(contained) != 1:
            reason = "ambiguous_segments"
        elif (
            not str(contained[0].get("id") or "")
            or structure_ids[str(contained[0]["id"])] != 1
        ):
            reason = "duplicate_structure_id"
        else:
            bindings.append(NumberedTableBinding(label, contained[0], cell))
        if reason:
            issues.append(NumberedTableIssue(cell.page_index, label, reason))
    ownership = Counter(str(binding.structure["id"]) for binding in bindings)
    unique_bindings = []
    for binding in bindings:
        if ownership[str(binding.structure["id"])] != 1:
            issues.append(
                NumberedTableIssue(
                    binding.cell.page_index, binding.label, "ambiguous_cell_ownership"
                )
            )
        else:
            unique_bindings.append(binding)
    return NumberedTableResult(
        tuple(sorted(set(recognized_pages) | {cell.page_index for cell in cells})),
        frozenset(observed_keys),
        tuple(unique_bindings),
        tuple(issues),
    )


def pair_numbered_table_cells(
    cells: Sequence[NumberedTableCell],
    structures: Sequence[Mapping[str, Any]],
    active_keys: set[str] | None = None,
    *,
    recognized_pages: Sequence[int] | set[int] = (),
) -> NumberedTableResult:
    """One source matcher; activity membership is an optional consumer filter only."""
    repeated = repeated_selected_catalogs(cells)
    pages = set(recognized_pages) | {cell.page_index for cell in cells}
    primary = _pair_cells(
        [cell for cell in cells if cell.catalog.identifier not in repeated],
        structures,
        active_keys,
        recognized_pages=pages,
    )
    confirmed = {binding.label for binding in primary.bindings}
    reprints: list[NumberedTableBinding] = []
    issues = list(primary.issues)
    for name in sorted(repeated):
        alternate = _pair_cells(
            [cell for cell in cells if cell.catalog.identifier == name],
            structures,
            None,
            recognized_pages=recognized_pages,
            # Only an explicitly proved selected subset can retain repeated
            # additional observations of an already-confirmed primary ID.
            repeatable_labels=frozenset(confirmed),
        )
        reprints.extend(
            binding for binding in alternate.bindings if binding.label in confirmed
        )
        issues.extend(alternate.issues)
    return NumberedTableResult(
        primary.recognized_pages,
        primary.observed_keys,
        primary.bindings,
        tuple(issues),
        tuple(reprints),
    )
