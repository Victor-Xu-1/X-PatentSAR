"""Exact prefixed diagram captions, never prose order or suffix inference."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .table_cells import prefixed_label, read_cell
from .table_geometry import page_tokens

Box = tuple[float, float, float, float]
_PREFIX = re.compile(
    r"(?:Example|Compound|Cmpd|Cpd|实施例|化合物)[-:.]?", re.IGNORECASE
)
_ID = re.compile(r"[1-9]\d{0,3}[A-Z]?", re.IGNORECASE)


@dataclass(frozen=True)
class CaptionBinding:
    label: str
    structure: Mapping[str, Any]
    label_bbox: Box
    observations: list[dict[str, Any]]


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
            if not _ID.fullmatch(str(other["text"])):
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
) -> list[CaptionBinding]:
    by_page: dict[int, list[Mapping[str, Any]]] = {}
    for structure in structures:
        page = structure.get("page_no")
        if type(page) is int and 1 <= page <= len(doc):
            by_page.setdefault(page, []).append(structure)
    identities = Counter(str(s.get("id") or "") for s in structures)
    bindings: list[CaptionBinding] = []
    for page_no, page_structures in sorted(by_page.items()):
        boxes = [
            _box([s.get(k) for k in ("x0", "y0", "x1", "y1")]) for s in page_structures
        ]
        # Unlocatable rival evidence cannot establish unique diagram ownership.
        if any(box is None for box in boxes):
            continue
        page = doc[page_no - 1]
        tokens = page_tokens(page, dpi=200, allow_tesseract=False)
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
            reading = read_cell(page, expanded, [token], "label", native)
            if not reading.needs_review and reading.value == label:
                candidates.append(
                    CaptionBinding(label, owners[0], bounds, reading.observations)
                )
        labels = Counter(b.label for b in candidates)
        owner_counts = Counter(str(b.structure["id"]) for b in candidates)
        bindings.extend(
            b
            for b in candidates
            if labels[b.label] == 1 and owner_counts[str(b.structure["id"])] == 1
        )
    counts = Counter(b.label for b in bindings)
    return [b for b in bindings if counts[b.label] == 1]
