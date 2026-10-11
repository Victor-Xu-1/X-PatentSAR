"""One source-identifier scope for SAR imports and historical result views."""

import re

_INTERMEDIATE = re.compile(
    r"^(?:intermediate(?=$|[\s_:.\-0-9])|interm[.\s_]|中间体)", re.IGNORECASE
)
_TEMPORARY = re.compile(
    r"^(?:source-structure:|编号待确认|未关联结构|关联结构\s+[a-f0-9]{6})",
    re.IGNORECASE,
)
_UNCONFIRMED = {"missing_or_invalid_identifier", "structure_number_unconfirmed"}


def source_exclusion(label: str, source_id: str | None = None, issues=()) -> str | None:
    if any(ord(char) < 32 for char in label):
        return "unconfirmed_identifier"
    label = label.strip()
    if (
        not label
        or len(label) > 200
        or any(ord(char) < 32 for char in label)
        or _TEMPORARY.match(label)
        or (source_id or "").startswith("source-structure:")
        or _UNCONFIRMED.intersection(issues)
    ):
        return "unconfirmed_identifier"
    if _INTERMEDIATE.match(label) or _INTERMEDIATE.match(source_id or ""):
        return "intermediate"
    return None


def included_molecules(molecules):
    return [
        row
        for row in molecules
        if source_exclusion(row.label, row.source_compound_id, row.issues) is None
    ]
