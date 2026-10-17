"""Explicit structure-catalog scope, separate from row geometry and chemistry."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Catalog:
    identifier: str = ""
    title: str = ""
    selected_subset: bool = False


def catalog_for_scope(scope) -> Catalog:
    """Use the same qualified original title as role and table-link consumers."""
    from .source_table_markers import caption_table_marker, table_marker_identity
    from .source_table_roles import observed_role
    from .structure_column_scopes import original_column_context
    from .unruled_continuation_titles import anchor_scope

    anchor = anchor_scope(scope)
    if anchor is None:
        return Catalog()
    packets = original_column_context(anchor)
    role, key = observed_role(packets)
    if role not in {"compound", "nonfinal"} or not key:
        return Catalog()
    texts = list(dict.fromkeys(packet["text"] for packet in packets))
    marker = caption_table_marker(texts[0])
    if marker is None:
        return Catalog()
    selected = {
        bool(re.search(r"\bselected\b|\bsubset\b|选定|选取", text, re.IGNORECASE))
        for text in texts
    }
    # A qualified original disagreement never grants selected-reprint exclusion.
    return Catalog(
        table_marker_identity(marker.group()),
        texts[0][:500],
        selected == {True},
    )


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
