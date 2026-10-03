"""Explicit structure-catalog scope, separate from row geometry and chemistry."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Catalog:
    identifier: str = ""
    title: str = ""
    selected_subset: bool = False


def catalog_marks(tokens: Sequence[Mapping[str, Any]]) -> list[tuple[float, Catalog]]:
    marks = []
    ordered = sorted(tokens, key=lambda t: (float(t["y"]), float(t["x"])))
    for index, token in enumerate(ordered):
        match = re.search(
            r"\bTable\s+([A-Z]|\d+)\s*[.:]\s*(.*)", str(token["text"]), re.I
        )
        if match is None:
            continue
        y = float(token["y"])
        nearby = " ".join(
            str(t["text"])
            for t in ordered[index : index + 4]
            if 0 <= float(t["y"]) - y <= 25
        )
        title = re.sub(r"\s+", " ", nearby).strip()[:500]
        marks.append(
            (
                y,
                Catalog(
                    f"Table {match.group(1).upper()}",
                    title,
                    bool(re.search(r"\bselected\b|\bsubset\b|选定|选取", title, re.I)),
                ),
            )
        )
    return marks


def catalog_at(
    marks: Sequence[tuple[float, Catalog]], y: float, prior: Catalog
) -> Catalog:
    preceding = [catalog for location, catalog in marks if location < y]
    return preceding[-1] if preceding else prior


def repeated_selected_catalogs(cells: Sequence[Any]) -> set[str]:
    """Ignore explicitly selected reprints only when a full catalog proves all IDs.

    Two full catalogs remain competing evidence. A selected table with novel IDs
    also remains independent evidence; title wording alone cannot erase it.
    """
    catalogs: dict[str, tuple[Catalog, set[str]]] = {}
    for cell in cells:
        catalog = cell.catalog
        label = str(cell.label).removesuffix(".").upper()
        if not catalog.identifier or not label:
            continue
        if catalog.identifier not in catalogs:
            catalogs[catalog.identifier] = catalog, set()
        catalogs[catalog.identifier][1].add(label)
    complete = [
        labels for catalog, labels in catalogs.values() if not catalog.selected_subset
    ]
    return {
        name
        for name, (catalog, labels) in catalogs.items()
        if catalog.selected_subset
        and labels
        and any(labels.issubset(full) for full in complete)
    }
