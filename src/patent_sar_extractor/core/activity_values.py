"""Shared activity-value semantics used across extraction, QA, and export."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

MISSING_ACTIVITY_VALUE_TOKENS = frozenset(
    {
        "NA",
        "ND",
        "NT",
        "NOTAVAILABLE",
        "NOTDETERMINED",
        "NOTTESTED",
        "UNTESTED",
    }
)


def normalize_activity_value_token(value: Any) -> str:
    """Normalize a value only for explicit-missing comparisons."""
    return re.sub(r"[\s._/-]+", "", str(value or "")).upper()


def is_explicit_missing_activity_value(value: Any) -> bool:
    """Return whether the source explicitly says no measurement is available."""
    return normalize_activity_value_token(value) in MISSING_ACTIVITY_VALUE_TOKENS


def _source_declares_missing_grade(field: str, value: Any, sources: Any) -> bool:
    """A grade is missing only through its matching original cell's legend.

    This is usability, not conversion of ordinal grades to concentrations.
    Conflicting or absent meanings remain unknown; raw values are never edited.
    """
    if not isinstance(sources, (list, tuple)):
        return False
    meanings = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        cells = source.get("cells", [])
        if not isinstance(cells, (list, tuple)) or not any(
            isinstance(cell, Mapping)
            and cell.get("field") == field
            and cell.get("value") == value
            for cell in cells
        ):
            continue
        legend = source.get("legend")
        meanings.append(
            legend.get(value)
            if isinstance(legend, Mapping) and isinstance(value, str)
            else None
        )
    return bool(meanings) and all(
        meaning is not None and is_explicit_missing_activity_value(meaning)
        for meaning in meanings
    )


def has_usable_activity_values(values: Any, *, sources: Any = ()) -> bool:
    """Return whether a mapping contains at least one measured activity value."""
    if not isinstance(values, Mapping):
        return False
    return any(
        str(value or "").strip()
        and not is_explicit_missing_activity_value(value)
        and not _source_declares_missing_grade(field, value, sources)
        for field, value in values.items()
    )
