"""Shared activity-value semantics used across extraction, QA, and export."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


MISSING_ACTIVITY_VALUE_TOKENS = frozenset({
    "NA",
    "ND",
    "NT",
    "NOTAVAILABLE",
    "NOTDETERMINED",
    "NOTTESTED",
    "UNTESTED",
})


def normalize_activity_value_token(value: Any) -> str:
    """Normalize a value only for explicit-missing comparisons."""
    return re.sub(r"[\s._/-]+", "", str(value or "")).upper()


def is_explicit_missing_activity_value(value: Any) -> bool:
    """Return whether the source explicitly says no measurement is available."""
    return normalize_activity_value_token(value) in MISSING_ACTIVITY_VALUE_TOKENS


def has_usable_activity_values(values: Any) -> bool:
    """Return whether a mapping contains at least one measured activity value."""
    if not isinstance(values, Mapping):
        return False
    return any(
        str(value or "").strip() and not is_explicit_missing_activity_value(value)
        for value in values.values()
    )
