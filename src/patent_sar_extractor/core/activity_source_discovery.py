"""Independent bounded source nomination from original/native cached evidence."""

from __future__ import annotations

import re

from .activity_header_metrics import METRIC, normalize_metric_text
from .activity_headers import ACTIVITY_CONTEXT, context_from_text
from .activity_source_roles import method_result_references, reported_method_source
from .source_section_roles import section_heading
from .source_table_markers import TABLE_MARKER

_CAPTION = re.compile(
    rf"^\s*(?:\[\s*\d{{1,8}}\s*\]\s*)?{TABLE_MARKER.pattern}",
    re.IGNORECASE | re.MULTILINE,
)
_ID_COLUMN = re.compile(
    r"(?:Compound|Cmpd|Cpd|Example|化合物|实施例)\s*(?:No\.?|ID|#|编号)|"
    r"^\s*(?:No\.|ID|编号)(?=\s|\||$)",
    re.IGNORECASE | re.MULTILINE,
)


def declared_activity_source(text: str) -> bool:
    """Nomination is not parsing or completeness acceptance; no numeric repair."""
    if not isinstance(text, str) or len(text) > 100000:
        raise ValueError("Original activity source text is outside bounds")
    for window in _original_windows(text):
        if reported_method_source(window):
            return True
        normalized = normalize_metric_text(window)
        if _ID_COLUMN.search(window) and METRIC.search(normalized):
            return True
        if _CAPTION.search(window):
            # A caption/continued title may nominate an unreadable source;
            # unrelated prose or a later assay must not rename its table.
            caption = context_from_text(window).raw_caption
            if ACTIVITY_CONTEXT.search(caption) or METRIC.search(
                normalize_metric_text(caption)
            ):
                return True
    return False


def reference_observations(text: str) -> list[dict]:
    """Independent method/result windows, even when another grid shares the page."""
    if not isinstance(text, str) or len(text) > 100000:
        raise ValueError("Original reference source text is outside bounds")
    result = []
    for window in _original_windows(text):
        if not reported_method_source(window):
            continue
        targets = method_result_references(window)
        result.append(
            {
                "header": window.strip()[:1024],
                "targets": targets,
                "status": "reference" if targets else "unresolved",
                "reason": "observed_result_references"
                if targets
                else "unsupported_result_reference",
            }
        )
    return result


def _original_windows(text: str):
    """Original table/section spans, not arbitrary overlapping character cuts.

    Nomination remains conservative and never certifies absence or completeness.
    Unknown section styles still require the independent classified/physical
    source checks. No rows, values or identifiers are manufactured here.
    """
    starts, offset = [0], 0
    for line in text.splitlines(keepends=True):
        if offset and (_CAPTION.match(line) or section_heading(line)):
            starts.append(offset)
        offset += len(line)
    for start, end in zip(starts, [*starts[1:], len(text)]):
        yield text[start:end]


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
