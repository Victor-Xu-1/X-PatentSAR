"""Lossless lexical interpretation of printed identifiers and cell values."""

from __future__ import annotations

import re

from .activity_values import is_explicit_missing_activity_value
from .measurement_literals import (
    MAX_NUMERIC_LITERAL_CHARS,
    NUMERIC_LITERAL_PATTERN,
    NumericLiteralError,
    parse_numeric_literal,
)
from .printed_identifiers import LABEL_PREFIX, PRINTED_ID, identifier_key

__all__ = [
    "CONTROL",
    "ID_HEADER",
    "LABEL_PREFIX",
    "PRINTED_ID",
    "is_control",
    "is_id_header",
    "is_numeric_value",
    "is_value",
    "normalize_compound",
    "normalize_value",
    "printed_identifier_key",
    "value_tokens",
]

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
_SOURCE_UNIT = r"nM|uM|µM|μM|mM|pM|mg/kg|ng/mL|h|min"
_COMMA_NUMBER = r"[+-]?\d+,\d+(?:[eE][+-]?\d+)?"
_LEGACY_NUMBER = r"[+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?"
_UNCERTAINTY = rf"(?:[<>≤≥]=?\s*)?{_LEGACY_NUMBER}%?\s*(?:±|\+/-)\s*\d+(?:\.\d+)?"
_COMMA_FORM = rf"(?:[<>≤≥]=?\s*)?{_COMMA_NUMBER}"
_NUMERIC_SOURCE = re.compile(
    rf"(?P<number>{_UNCERTAINTY}|{_COMMA_FORM}|{NUMERIC_LITERAL_PATTERN})"
    rf"(?P<unit>%|\s*(?:{_SOURCE_UNIT}))?",
    re.IGNORECASE,
)
_OTHER_VALUE = re.compile(r"∞|[A-G](?:[12])?|\+{1,5}|-{1,3}", re.IGNORECASE)
_VALUE_TOKEN = re.compile(
    rf"{_NUMERIC_SOURCE.pattern}|not\s+tested|not\s+determined|not\s+available|"
    r"未测试|未测定|未检测|N/?A|ND|NT|[-—–]|∞|[A-G](?:[12])?|\+{1,5}",
    re.IGNORECASE,
)


def normalize_compound(value: str) -> str:
    """Canonicalize only the label wrapper, never its digits, prefix or suffix."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if CONTROL.fullmatch(text):
        return text
    key = identifier_key(text, wrapped=True)
    if key:
        return f"Compound {key}"
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
        text
        and len(text) <= MAX_NUMERIC_LITERAL_CHARS
        and (
            is_explicit_missing_activity_value(text)
            or _OTHER_VALUE.fullmatch(text)
            or is_numeric_value(text)
        )
    )


def is_numeric_value(value: str) -> bool:
    """Recognize a complete source measurement without interpreting its unit.

    Decimal-comma and uncertainty spellings retain their prior extraction-only
    status. Resource checks never turn either into a scalar SAR observation.
    """
    text = normalize_value(value)
    if len(text) > MAX_NUMERIC_LITERAL_CHARS:
        return False
    match = _NUMERIC_SOURCE.fullmatch(text)
    if match is None:
        return False
    number = match["number"]
    try:
        if re.fullmatch(_UNCERTAINTY, number, re.IGNORECASE):
            center, spread = re.split(r"\s*(?:±|\+/-)\s*", number)
            parse_numeric_literal(center.rstrip("%").replace(",", "."))
            parse_numeric_literal(spread)
        elif re.fullmatch(_COMMA_FORM, number):
            parse_numeric_literal(number.replace(",", "."))
        else:
            parse_numeric_literal(number)
    except NumericLiteralError:
        return False
    return True


def value_tokens(text: str) -> list[str] | None:
    """Consume the complete row tail, not arbitrary numeric substrings of prose."""
    result = []
    position = 0
    while position < len(text):
        separator = re.match(r"[\s,;]+", text[position:])
        if separator:
            position += separator.end()
            continue
        match = _VALUE_TOKEN.match(text, position)
        if not match or (match.end() < len(text) and not text[match.end()].isspace()):
            return None
        value = normalize_value(match.group())
        if not is_value(value) and value not in {"—", "–"}:
            return None
        result.append(value)
        position = match.end()
    return result
