"""Literal table-caption typography, independent of chemical or assay meaning."""

import re

# Common OCR l/i/1 confusion affects the word Table, never the printed number.
# Raw captions remain source evidence; this marker supplies discovery/identity.
TABLE_MARKER = re.compile(
    r"\bTab[li1]e\s*[A-Za-z]?\d+[A-Za-z]?\b|表\s*\d+[A-Za-z]?", re.IGNORECASE
)
TABLE_CAPTION_START = re.compile(r"^(?:Tab[li1]e(?:\b|(?=\d))|表\s*\d)", re.IGNORECASE)


def table_marker_identity(marker: str) -> str:
    return re.sub(r"^Tab[li1]e\s*", "Table ", marker, flags=re.IGNORECASE)
