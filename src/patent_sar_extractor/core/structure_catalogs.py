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
    namespace: str = ""


def _selected_title(text):
    from .source_role_terms import role_words

    text = role_words(text)
    if not re.search(
        r"\bselected\b|\bsubset\b|选定|選定|选取|選取", text, re.IGNORECASE
    ):
        return False
    return not re.search(
        r"\b(?:not\s+|non[-\s]+|un)selected\b|\bnot\s+(?:a\s+)?subset\b"
        r"|\b(?:and|or|versus|vs\.?|with)\s+(?:the\s+)?(?:remaining|other|unselected|all)\b"
        r"|(?:未|非)(?:选定|選定|选取|選取)|(?:和|与|與|及).*(?:其余|其餘|其他|其它|全部)",
        text,
        re.IGNORECASE,
    )


def _catalog_from_titles(texts) -> Catalog:
    from .caption_role_semantics import catalog_title_namespace
    from .source_table_markers import caption_table_marker, table_marker_identity
    from .source_table_roles import title_key

    texts = tuple(dict.fromkeys(texts))
    if not texts or len({title_key(text) for text in texts}) != 1:
        return Catalog()
    marker = caption_table_marker(texts[0])
    if marker is None:
        return Catalog()
    selected = {_selected_title(text) for text in texts}
    namespaces = {catalog_title_namespace(text) for text in texts}
    return Catalog(
        table_marker_identity(marker.group()),
        texts[0][:500],
        selected == {True},
        next(iter(namespaces)) if len(namespaces) == 1 else "",
    )


def catalog_for_scope(scope) -> Catalog:
    """Use the same qualified original title as role and table-link consumers."""
    from .source_table_roles import observed_role, title_texts
    from .structure_column_scopes import (
        original_column_context,
        original_column_title_args,
    )
    from .unruled_continuation_titles import anchor_scope

    anchor = anchor_scope(scope)
    if anchor is None:
        return Catalog()
    packets = original_column_context(anchor)
    title_args = original_column_title_args(anchor)
    role, key = observed_role(packets, **title_args)
    if role not in {"compound", "nonfinal"} or not key:
        return Catalog()
    # A qualified original disagreement never grants selected-reprint exclusion.
    return _catalog_from_titles(title_texts(packets, **title_args))


def catalog_for_caption_scope(scope) -> Catalog:
    """Revalidate the complete original role before using selected-table words."""
    from .caption_role_links import MAX_CONTINUATION_DEPTH
    from .caption_role_proof import caption_role_status
    from .source_table_roles import title_texts
    from .title_context_grids import caption_title_context

    if (
        not isinstance(scope, dict)
        or caption_role_status(scope, scope.get("page_no"), scope.get("table_bbox"))
        != "compound"
    ):
        return Catalog()
    # The role replay above already validates every linked boundary and title.
    for _ in range(MAX_CONTINUATION_DEPTH + 1):
        if "continuation" not in scope:
            break
        scope = scope["continuation"]["previous"]
    else:
        return Catalog()
    return _catalog_from_titles(
        title_texts(
            scope["observations"],
            contexts=scope["sources"],
            context=caption_title_context(scope),
        )
    )


def repeated_selected_catalogs(cells: Sequence[Any]) -> set[str]:
    """Ignore explicitly selected reprints only when a full catalog proves all IDs.

    Two full catalogs remain competing evidence. A selected table with novel IDs
    also remains independent evidence; title wording alone cannot erase it.
    """
    catalogs: dict[str, tuple[set[bool], set[str]]] = {}
    for cell in cells:
        catalog = cell.catalog
        label = str(cell.label).removesuffix(".").upper()
        if not catalog.identifier or not label:
            continue
        if catalog.identifier not in catalogs:
            catalogs[catalog.identifier] = set(), set()
        catalogs[catalog.identifier][0].add(catalog.selected_subset)
        catalogs[catalog.identifier][1].add(label)
    complete = [labels for roles, labels in catalogs.values() if roles == {False}]
    return {
        name
        for name, (roles, labels) in catalogs.items()
        if roles == {True}
        and labels
        and any(labels.issubset(full) for full in complete)
    }
