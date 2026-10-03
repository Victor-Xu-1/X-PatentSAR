"""Original-cell ownership for numbered, ruled compound/structure tables.

Grid detection and cell OCR are shared with activity extraction. This module
neither reconstructs a global sequence nor fills missing/letter-suffixed IDs.
Recognized table pages remain protected even when none of their cells bind.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .structure_catalogs import (
    Catalog,
    catalog_at,
    catalog_marks,
    repeated_selected_catalogs,
)

Box = tuple[float, float, float, float]
_ID_RE = re.compile(r"[1-9]\d{0,3}[A-Z]?\.?", re.I)
_HEADER_RE = re.compile(r"(?:Cmpd|Cpd|Compound|Example)\.?\s*(?:No\.?|ID|#)", re.I)


class _CellReading(Protocol):
    value: str
    observations: list[dict[str, Any]]
    needs_review: bool


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
    catalog: Catalog = Catalog()


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

    @property
    def recognized(self) -> bool:
        return bool(self.recognized_pages)


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
        flags=re.I,
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


def pair_numbered_table_cells(
    cells: Sequence[NumberedTableCell],
    structures: Sequence[Mapping[str, Any]],
    active_keys: set[str],
    *,
    recognized_pages: Sequence[int] | set[int] = (),
) -> NumberedTableResult:
    """Require one printed ID and one complete segment in its adjacent cell."""
    ignored_catalogs = repeated_selected_catalogs(cells)
    cells = [cell for cell in cells if cell.catalog.identifier not in ignored_catalogs]
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
        elif observed[label] != 1:
            reason = "duplicate_label"
        elif not _adjacent_cells(label_box, cell_box):
            reason = "invalid_cell_geometry"
        if reason:
            issues.append(NumberedTableIssue(cell.page_index, label, reason))
            continue
        if label not in active_keys:
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
        b <= a for axis in (xs, ys) for a, b in zip(axis, axis[1:])
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
    active_keys: set[str],
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
    if not page_indices or not active_keys:
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
                        and re.search(r"\bStructure\b", right, re.I)
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
                    re.I,
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
