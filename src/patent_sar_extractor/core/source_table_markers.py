"""Literal table-caption typography, independent of chemical or assay meaning."""

import re

# Common OCR l/i/1 confusion affects the word Table, never the printed number.
# Raw captions remain source evidence; this marker supplies discovery/identity.
TABLE_INDEX = r"(?:[A-Za-z][-–—]?)?\d+(?:[-–—]\d+)*[A-Za-z]?"
TABLE_MARKER = re.compile(
    rf"\bTab[li1]e(?:\s*{TABLE_INDEX}|\s+[A-Za-z])\b(?![-–—])"
    rf"|表\s*(?:{TABLE_INDEX}|[A-Za-z])(?![A-Za-z0-9–—-])",
    re.IGNORECASE,
)
TABLE_CAPTION_START = re.compile(
    r"^\s*(?:\[\s*\d{1,8}\s*\]\s*)?"
    rf"(?:Tab[li1]e(?:\b|(?={TABLE_INDEX}\b(?![-–—])))|"
    r"表(?=\s|[0-9A-Za-z一二三四五六七八九十甲乙丙丁]))",
    re.IGNORECASE,
)


def caption_table_marker(text):
    """A paragraph locator may precede a real title, never arbitrary prose."""
    if not isinstance(text, str):
        return None
    start = TABLE_CAPTION_START.match(text)
    marker = TABLE_MARKER.search(text) if start else None
    return marker if marker and marker.start() < start.end() <= marker.end() else None


def table_marker_identity(marker: str) -> str:
    return re.sub(r"^Tab[li1]e\s*", "Table ", marker, flags=re.IGNORECASE)
