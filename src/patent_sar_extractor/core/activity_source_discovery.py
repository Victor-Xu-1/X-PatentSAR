"""Independent bounded source nomination from original/native cached evidence."""

from __future__ import annotations

import re

from .activity_header_metrics import METRIC, normalize_metric_text
from .activity_headers import ACTIVITY_CONTEXT
from .source_table_markers import TABLE_MARKER

_CAPTION = re.compile(
    rf"^\s*(?:\[\s*\d{{1,8}}\s*\]\s*)?{TABLE_MARKER.pattern}",
    re.IGNORECASE | re.MULTILINE,
)
_ID_COLUMN = re.compile(
    r"(?:Compound|Cmpd|Cpd|Example|化合物|实施例)\s*(?:No\.?|ID|#|编号)|"
    r"^\s*(?:No\.|ID|编号)(?=\s|$)",
    re.IGNORECASE | re.MULTILINE,
)


def declared_activity_source(text: str) -> bool:
    """Nomination is not parsing or completeness acceptance; no numeric repair."""
    if not isinstance(text, str) or len(text) > 100000:
        raise ValueError("Original activity source text is outside bounds")
    normalized = normalize_metric_text(text)
    if _ID_COLUMN.search(text) and METRIC.search(normalized):
        return True
    return any(
        ACTIVITY_CONTEXT.search(window) or METRIC.search(normalize_metric_text(window))
        for marker in _CAPTION.finditer(text)
        for window in [text[marker.start() : marker.start() + 3000]]
    )


def discover_activity_sources(doc, text_map: dict[str, str]) -> list[int]:
    """Read cheap native text; reuse original OCR cache, never start a new model."""
    if not 1 <= len(doc) <= 10000:
        raise ValueError("Original activity source page count is outside bounds")
    pages = []
    for index, page in enumerate(doc):
        native = page.get_text("text")
        cached = str(text_map.get(str(index), "") or "")
        if declared_activity_source(native) or declared_activity_source(cached):
            pages.append(index)
    return pages
