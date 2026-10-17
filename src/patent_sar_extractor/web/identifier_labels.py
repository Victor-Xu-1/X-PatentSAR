"""Read-only patent-owned identifier labels, separate from stable join keys."""

from __future__ import annotations

import re

from patent_sar_extractor.core.activity_identity import (
    is_control,
    normalize_compound,
    printed_identifier_key,
)

from .models import Compound


def _generated_reference(row: Compound) -> bool:
    correction = row.correction
    if correction and (
        correction.identifier_changed is True
        or (correction.has_changes and correction.identifier_changed is None)
    ):
        # An old overlay without effective rename metadata is not a license
        # to translate a possibly user-owned name.
        return False
    if (
        row.record_kind != "structure_only"
        or row.source.source_label is not None
        or not {"unassociated_structure", "structure_number_unconfirmed"}.issubset(
            row.flags
        )
        or not re.fullmatch(r"source-structure:[a-f0-9]{32}(?::\d+)?", row.id)
    ):
        return False
    reference = row.structure_id or row.id.rsplit(":", 1)[-1][-8:]
    return row.display_id == f"编号待确认 {reference}"


def identifier_label(row: Compound) -> str | None:
    # Absence of a literal source identifier lets the UI localize only its
    # application-owned placeholder. Never rewrite the stored display field.
    if _generated_reference(row):
        return None
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
