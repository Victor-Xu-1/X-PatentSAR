"""Literal table-caption typography, independent of chemical or assay meaning."""

import re

from .source_paragraphs import PARAGRAPH_LOCATOR

# Common OCR l/i/1 confusion affects the word Table, never the printed number.
# Raw captions remain source evidence; this marker supplies discovery/identity.
TABLE_INDEX = r"(?:[A-Za-z][-–—]?)?\d+(?:[-–—]\d+)*[A-Za-z]?"
TABLE_MARKER = re.compile(
    rf"\bTab[li1]e(?:\s*{TABLE_INDEX}|\s+[A-Za-z])\b(?![-–—])"
    rf"|表\s*(?:{TABLE_INDEX}|[A-Za-z])(?![A-Za-z0-9–—-])",
    re.IGNORECASE,
)
TABLE_CAPTION_START = re.compile(
    rf"^\s*(?:{PARAGRAPH_LOCATOR}\s*)?"
    rf"(?:Tab[li1]e(?:\b|(?={TABLE_INDEX}\b(?![-–—])))|"
    r"表(?=\s|[0-9A-Za-z一二三四五六七八九十甲乙丙丁]))",
    re.IGNORECASE,
)
TABLE_CAPTION_LINE = re.compile(
    rf"^[ \t]*(?:{PARAGRAPH_LOCATOR}[ \t]*)?(?:{TABLE_MARKER.pattern})",
    re.IGNORECASE | re.MULTILINE,
)
# A broken numeric paragraph prefix is a source fence, not a proved caption.
# Keep brackets/digits literal; isotope/prose prefixes never gain this role.
_UNPROVED_LOCATOR = r"[\[［](?=[\d\[\]［］ \t]*\d)[\d\[\]［］ \t]*"
TABLE_BOUNDARY_LINE = re.compile(
    # The unproved locator already owns whitespace; a second trailing quantifier
    # would backtrack quadratically on a long numeric prefix without a caption.
    rf"^[ \t]*(?:{PARAGRAPH_LOCATOR}[ \t]*|{_UNPROVED_LOCATOR})?"
    rf"(?:{TABLE_MARKER.pattern})",
    re.IGNORECASE | re.MULTILINE,
)


def unproved_caption_prefix(text: str) -> bool:
    """Withhold a numeric-prefix boundary without repairing its printed source."""
    return bool(TABLE_BOUNDARY_LINE.match(text) and not TABLE_CAPTION_LINE.match(text))


def table_body_boundary(text: str) -> bool:
    """Nominate a literal or uncertain title, never grant its role or identity."""
    return bool(TABLE_CAPTION_START.match(text)) or unproved_caption_prefix(text)


def caption_table_marker(text):
    """A paragraph locator may precede a real title, never arbitrary prose."""
    if not isinstance(text, str):
        return None
    start = TABLE_CAPTION_START.match(text)
    marker = TABLE_MARKER.search(text) if start else None
    return marker if marker and marker.start() < start.end() <= marker.end() else None


def table_marker_identity(marker: str) -> str:
    return re.sub(r"^Tab[li1]e\s*", "Table ", marker, flags=re.IGNORECASE)


def title_row_indices(rows, *, boundary=table_body_boundary):
    """One last-caption and two adjacent continuation-row selector."""
    starts = [index for index, row in enumerate(rows) if boundary(row["text"])]
    if not starts:
        return []
    numbered = [index for index in starts if table_body_boundary(rows[index]["text"])]
    start = numbered[-1] if numbered else starts[-1]
    if not numbered:
        for _ in range(2):
            previous = start - 1
            if (
                previous not in starts
                or rows[start]["bbox"][1] - rows[previous]["bbox"][3] > 18
            ):
                break
            start = previous
    selected = [start]
    for index in range(start + 1, min(len(rows), start + 3)):
        if rows[index]["bbox"][1] - rows[selected[-1]]["bbox"][
            3
        ] > 18 or table_body_boundary(rows[index]["text"]):
            break
        selected.append(index)
    return selected
