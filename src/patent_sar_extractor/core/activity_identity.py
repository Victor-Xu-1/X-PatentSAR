"""Lossless lexical interpretation of printed identifiers and cell values."""

from __future__ import annotations

import re

from .activity_values import is_explicit_missing_activity_value

PRINTED_ID = r"(?:[A-Za-z]{1,12}-)?\d{1,8}(?:-\d{1,8})*[A-Za-z]{0,4}"
LABEL_PREFIX = r"(?:Compound|Cmpd|Cpd|Example|实施例|化合物)\s*[-:.：]?\s*"
CONTROL = re.compile(
    r"(?:Ref\.?\s*\d+|Reference(?:\s+\S+)?|Vehicle|DMSO|Control|"
    r"Nab[-\s]?paclitaxel|Paclitaxel)",
    re.IGNORECASE,
)
ID_HEADER = re.compile(
    r"(?:Compound|Cmpd|Cpd|Example|实施例|化合物)\s*(?:No\.?|ID|#|编号|号)?|"
    r"No\.?|ID|编号|受试物|药物名称|[A-Za-z]-#",
    re.IGNORECASE,
)
_LABEL = re.compile(rf"(?:{LABEL_PREFIX})?({PRINTED_ID})", re.IGNORECASE)
_VALUE = re.compile(
    r"(?:[<>≤≥]=?\s*)?[-+]?\d+(?:[.,]\d+)?(?:[Ee][-+]?\d+)?%?"
    r"(?:\s*(?:±|\+/-)\s*\d+(?:\.\d+)?)?"
    r"(?:\s*(?:nM|uM|µM|μM|mM|pM|mg/kg|ng/mL|h|min))?"
    r"|∞|[A-G](?:[12])?|\+{1,5}|-{1,3}",
    re.IGNORECASE,
)


def normalize_compound(value: str) -> str:
    """Canonicalize only the label wrapper, never its digits, prefix or suffix."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if CONTROL.fullmatch(text):
        return text
    match = _LABEL.fullmatch(text)
    if match:
        return f"Compound {match.group(1)}"
    return ""


def printed_identifier_key(value: object) -> str:
    """One exact proof key; never search hashes, prose or composite measurements."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if text.upper() == "CLAIM1" or re.fullmatch(
        r"(?:claim\s*1\s+compound|claimed\s+compound|main\s+compound|single(?:ton)?\s+compound)",
        text,
        re.IGNORECASE,
    ):
        return "CLAIM1"  # Read-only legacy identity; not a new printed-ID proof.
    normalized = normalize_compound(text)
    return normalized.removeprefix("Compound ").upper() if normalized else ""


def is_control(value: str) -> bool:
    return bool(CONTROL.fullmatch(str(value or "").strip()))


def is_id_header(value: str) -> bool:
    return bool(ID_HEADER.fullmatch(re.sub(r"\s+", " ", value).strip()))


def normalize_value(value: str) -> str:
    # Unicode glyph variants have explicit equivalents. No digit, comparator,
    # decimal point, threshold, grade count or unit is inferred.
    return str(value or "").strip().replace("＋", "+").replace("％", "%")


def is_value(value: str) -> bool:
    text = normalize_value(value)
    return bool(
        text and (is_explicit_missing_activity_value(text) or _VALUE.fullmatch(text))
    )


def value_tokens(text: str) -> list[str] | None:
    """Consume the complete row tail, not arbitrary numeric substrings of prose."""
    token = re.compile(
        r"not\s+tested|not\s+determined|not\s+available|未测试|未测定|未检测|"
        r"N/?A|ND|(?:[<>≤≥]=?\s*)?[-+]?\d+(?:[.,]\d+)?(?:[Ee][-+]?\d+)?%?"
        r"(?:\s*(?:±|\+/-)\s*\d+(?:\.\d+)?)?|[-—–]|∞|[A-G](?:[12])?|\+{1,5}",
        re.IGNORECASE,
    )
    result = []
    position = 0
    while position < len(text):
        separator = re.match(r"[\s,;]+", text[position:])
        if separator:
            position += separator.end()
            continue
        match = token.match(text, position)
        if not match or (match.end() < len(text) and not text[match.end()].isspace()):
            return None
        result.append(normalize_value(match.group()))
        position = match.end()
    return result
