"""Read-only patent-owned identifier labels, separate from stable join keys."""

from __future__ import annotations

from patent_sar_extractor.core.activity_identity import (
    is_control,
    normalize_compound,
    printed_identifier_key,
)

from .models import Compound


def identifier_label(row: Compound) -> str:
    # Audited explicit renames remain visible, without changing the original ID.
    if row.display_id != row.id:
        return row.display_id
    label = row.source.source_label
    key = printed_identifier_key(row.id)
    if (
        label
        and len(label.strip()) <= 200
        and key
        and printed_identifier_key(label.strip().rstrip(".:。")) == key
    ):
        return label.strip()
    # Compound is the internal canonical wrapper, not a label to impose on PDFs.
    normalized = normalize_compound(row.display_id)
    if normalized and not is_control(normalized):
        return normalized.removeprefix("Compound ")
    # An unproved structure reference is never relabelled as a guessed number.
    return row.display_id


def identifier_equal(left: object, right: object) -> bool:
    """Legacy canonical-filter aliases, never a guessed source/entity merge."""
    if str(left).casefold() == str(right).casefold():
        return True
    first, second = printed_identifier_key(left), printed_identifier_key(right)
    return bool(first and first == second)
