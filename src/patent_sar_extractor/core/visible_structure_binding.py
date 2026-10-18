"""Exact prefixed diagram captions, never prose order or suffix inference."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .caption_grid_binding import CaptionGridResult, bind_caption_grids
from .printed_identifiers import LABEL_KIND, identifier_key
from .table_cells import prefixed_label, read_cell
from .table_geometry import page_tokens

Box = tuple[float, float, float, float]
_PREFIX = re.compile(rf"{LABEL_KIND}[-:.：]?", re.IGNORECASE)


@dataclass(frozen=True)
class CaptionBinding:
    label: str
    structure: Mapping[str, Any]
    label_bbox: Box
    observations: list[dict[str, Any]]
    label_page_no: int | None = None
    ownership: dict = field(default_factory=dict)


def _box(values: Sequence[Any]) -> Box | None:
    if len(values) != 4 or any(isinstance(v, bool) for v in values):
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in values)
    except (ValueError, TypeError, OverflowError):
        return None
    if not all(math.isfinite(v) and v >= 0 for v in (x0, y0, x1, y1)):
        return None
    return (x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None


def _caption_tokens(tokens: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join native prefix/ID words only when their original baselines touch."""
    captions = [t for t in tokens if prefixed_label(str(t["text"]))]
    for token in tokens:
        if not _PREFIX.fullmatch(str(token["text"])):
            continue
        bounds = _box(token.get("bbox", []))
        if bounds is None:
            continue
        adjacent = []
        for other in tokens:
            if not identifier_key(other["text"]):
                continue
            box = _box(other.get("bbox", []))
            if (
                box
                and 0 <= box[0] - bounds[2] <= 14
                and abs(float(other["y"]) - float(token["y"])) <= 3
            ):
                adjacent.append((other, box))
        if len(adjacent) != 1:
            continue
        other, box = adjacent[0]
        joined = (bounds[0], min(bounds[1], box[1]), box[2], max(bounds[3], box[3]))
        captions.append(
            {
                "text": f"{token['text']} {other['text']}",
                "bbox": joined,
                "x": (joined[0] + joined[2]) / 2,
                "y": (joined[1] + joined[3]) / 2,
            }
        )
    return captions


def bind_visible_captions(
    doc: Any,
    structures: Sequence[Mapping[str, Any]],
    active: set[str] | None,
    *,
    excluded: set[str] | frozenset[str] = frozenset(),
    source_pages: Sequence[int] | None = None,
    recognized_pages: set[int] | None = None,
    observed_labels: set[str] | None = None,
    issues: list[dict] | None = None,
    source_exclusions: list[dict] | None = None,
    protected_structure_ids: set[str] | None = None,
    withheld_structure_ids: frozenset[str] = frozenset(),
    grids_for_page=None,
    tokens_for_page=None,
    grid_result: CaptionGridResult | None = None,
) -> list[CaptionBinding]:
    by_page: dict[int, list[Mapping[str, Any]]] = {}
    for structure in structures:
        page = structure.get("page_no")
        if type(page) is int and 1 <= page <= len(doc):
            by_page.setdefault(page, []).append(structure)
    identities = Counter(str(s.get("id") or "") for s in structures)
    boxes_by_page = {
        p: [_box([s.get(k) for k in ("x0", "y0", "x1", "y1")]) for s in items]
        for p, items in by_page.items()
    }
    catalog = (
        grid_result
        if grid_result is not None
        else bind_caption_grids(
            doc,
            by_page,
            boxes_by_page,
            [p + 1 for p in source_pages]
            if source_pages is not None
            else sorted(by_page),
            grids_for_page=grids_for_page,
            tokens_for_page=tokens_for_page,
        )
    )
    if recognized_pages is not None:
        recognized_pages.update(p - 1 for p in catalog.pages)
    if observed_labels is not None:
        observed_labels.update(catalog.labels)
    if issues is not None:
        issues.extend(catalog.issues)
    if source_exclusions is not None:
        source_exclusions.extend(catalog.exclusions)
    if protected_structure_ids is not None:
        protected_structure_ids.update(catalog.protected_structure_ids)
    bindings = [
        CaptionBinding(**item)
        for item in catalog.bindings
        if (grid_result is not None or item["label"] not in excluded)
        and str(item["structure"].get("id") or "") not in withheld_structure_ids
        and (active is None or item["label"] in active)
        and identities[str(item["structure"].get("id") or "")] == 1
    ]
    for page_no, page_structures in sorted(by_page.items()):
        page_structures = [
            s
            for s in page_structures
            if str(s.get("id") or "") not in catalog.protected_structure_ids
            and str(s.get("id") or "") not in withheld_structure_ids
        ]
        if not page_structures:
            continue
        boxes = [
            _box([s.get(k) for k in ("x0", "y0", "x1", "y1")]) for s in page_structures
        ]
        # Unlocatable rival evidence cannot establish unique diagram ownership.
        if any(box is None for box in boxes):
            continue
        page = doc[page_no - 1]
        tokens = catalog.tokens.get(page_no)
        if tokens is None:
            tokens = (
                tokens_for_page(page)
                if tokens_for_page
                else page_tokens(page, dpi=200, allow_tesseract=False)
            )
        native = bool(page.get_text("words"))
        candidates = []
        for token in _caption_tokens(tokens):
            label = prefixed_label(str(token["text"]))
            bounds = _box(token.get("bbox", []))
            if (
                not label
                or label in excluded
                or (active is not None and label not in active)
                or bounds is None
            ):
                continue
            x, y = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
            if any(
                cell[0] <= x < cell[2] and cell[1] <= y < cell[3]
                for cell in catalog.regions.get(page_no, [])
            ):
                continue
            owners = [
                s
                for s, box in zip(page_structures, boxes)
                if box is not None
                and box[0] <= x <= box[2]
                and box[3] - 32 <= y <= box[3] + 24
            ]
            if len(owners) != 1:
                continue
            identity = str(owners[0].get("id") or "")
            if not identity or identities[identity] != 1:
                continue
            expanded = (
                max(0, bounds[0] - 4),
                max(0, bounds[1] - 4),
                min(page.rect.width, bounds[2] + 4),
                min(page.rect.height, bounds[3] + 4),
            )
            reading = read_cell(page, expanded, tokens, "label", native)
            if not reading.needs_review and reading.value == label:
                candidates.append(
                    CaptionBinding(
                        label, owners[0], bounds, reading.observations, page_no
                    )
                )
        labels = Counter(b.label for b in candidates)
        owner_counts = Counter(str(b.structure["id"]) for b in candidates)
        bindings.extend(
            b
            for b in candidates
            if labels[b.label] == 1 and owner_counts[str(b.structure["id"])] == 1
        )
    # Keep independently proved cell observations. The sole document-wide source
    # claim authority distinguishes selected reprints from competing catalogues.
    return bindings
