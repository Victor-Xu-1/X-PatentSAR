"""Literal table-caption typography, independent of chemical or assay meaning."""

import re

# Common OCR l/i/1 confusion affects the word Table, never the printed number.
# Raw captions remain source evidence; this marker supplies discovery/identity.
_TABLE_INDEX = r"(?:[A-Za-z][-–—]?)?\d+(?:[-–—]\d+)*[A-Za-z]?"
TABLE_MARKER = re.compile(
    rf"\bTab[li1]e(?:\s*{_TABLE_INDEX}|\s+[A-Za-z])\b(?![-–—])"
    rf"|表\s*(?:{_TABLE_INDEX}|[A-Za-z])(?![A-Za-z0-9–—-])",
    re.IGNORECASE,
)
TABLE_CAPTION_START = re.compile(
    r"^(?:Tab[li1]e(?:\b|(?=\d))|表\s*(?:\d|[A-Za-z]))", re.IGNORECASE
)


def table_marker_identity(marker: str) -> str:
    return re.sub(r"^Tab[li1]e\s*", "Table ", marker, flags=re.IGNORECASE)
