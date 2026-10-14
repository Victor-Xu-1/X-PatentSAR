"""Literal running/continued-caption and physical column rules, not inference."""

import re

from .activity_header_metrics import normalize_metric_text
from .source_table_markers import TABLE_MARKER, table_marker_identity


def continuation_prefix(prefix: str) -> bool:
    document_id = r"(?:WO|PCT|US|EP|CN|JP|KR)\s*/?(?:[A-Z]{1,4})?\d[\w/-]*"
    running = re.compile(
        rf"{document_id}(?:\s+{document_id})*|[-–—]?\s*\d+\s*[-–—]?", re.IGNORECASE
    )
    return all(
        running.fullmatch(line.strip()) for line in prefix.splitlines() if line.strip()
    )


def canonical_header(text: str) -> str:
    return re.sub(r"\s+", "", normalize_metric_text(text))


def caption_prefix(
    prefix: str, table_id: str, original_caption: str, *, continued=False
) -> bool:
    lines = [
        line.strip()
        for line in prefix.splitlines()
        if line.strip() and not continuation_prefix(line)
    ]
    text = " ".join(lines)
    if not text:
        return not continued
    markers = list(TABLE_MARKER.finditer(text))
    if (
        len(markers) != 1
        or table_marker_identity(markers[0].group()).casefold() != table_id.casefold()
    ):
        return False
    term = re.compile(
        r"\(?\b(?:continued|cont\.?|cont['’]d)\b\)?|续表|（续）|\(续\)", re.IGNORECASE
    )
    if continued and not term.search(text):
        return False
    clean = term.sub("", text).strip(" .:：-()（）")
    original = original_caption.strip(" .:：-()（）")
    return canonical_header(clean) in {
        canonical_header(original),
        canonical_header(table_id),
    }


def compatible_columns(a, b, *, relative=False) -> bool:
    if len(a) != len(b):
        return False
    return all(
        abs((x - (a[0] if relative else 0)) - (y - (b[0] if relative else 0))) <= 4
        for x, y in zip(a, b)
    )


def continuation_allowed(prefix, previous_layout, context) -> bool:
    explicit = caption_prefix(
        prefix, context.table_id, context.raw_caption, continued=True
    )
    return (continuation_prefix(prefix) or explicit) and (
        previous_layout is None or continuation_prefix(previous_layout["suffix"])
    )
