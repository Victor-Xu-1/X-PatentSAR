"""One source-identifier scope for SAR imports and historical result views."""

import re

from ...core.source_role_terms import INTERMEDIATE_CJK

_INTERMEDIATE = re.compile(
    rf"^(?:intermediate(?=$|[\s_:.\-0-9])|interm[.\s_]|{INTERMEDIATE_CJK})",
    re.IGNORECASE,
)
_TEMPORARY = re.compile(
    r"^(?:source-structure:|编号待确认|未关联结构|关联结构\s+[a-f0-9]{6})",
    re.IGNORECASE,
)
_UNCONFIRMED = {"missing_or_invalid_identifier", "structure_number_unconfirmed"}
# Exact missing-cell markers only. Do not infer a numbering grammar or reject
# real source labels merely because they contain a marker (e.g. NA-1 or I-255).
_MISSING_NUMBER = frozenset(
    {
        "-",
        "--",
        "—",
        "–",
        "n/a",
        "nan",
        "none",
        "null",
        "undefined",
        "unnumbered",
        "unassigned",
        "无编号",
        "未编号",
        "编号缺失",
        "编号待定",
    }
)


def source_exclusion(label: str, source_id: str | None = None, issues=()) -> str | None:
    if any(ord(char) < 32 for char in label):
        return "unconfirmed_identifier"
    label = label.strip()
    if (
        not label
        or label.casefold() in _MISSING_NUMBER
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
