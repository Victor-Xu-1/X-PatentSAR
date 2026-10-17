"""Literal running/continued-caption and physical column rules, not inference."""

import re

from .activity_header_metrics import normalize_metric_text
from .activity_headers import context_source_text
from .source_table_markers import caption_table_marker, table_marker_identity


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
    if continued:
        boundary = "\n".join(
            line.strip()
            for line in prefix.splitlines()
            if line.strip() and not continuation_prefix(line)
        )
        if caption_table_marker(boundary) is None:
            return False  # A new section/procedure cannot disappear before carry.

    def original_context(value):
        # Use the same real-caption boundary that owns parsed assay fields.
        # Earlier prose references are retained as provenance, not new titles.
        return " ".join(
            line.strip()
            for line in context_source_text(value).splitlines()
            if line.strip() and not continuation_prefix(line)
        )

    text = original_context(prefix)
    if not text:
        return False  # An absent caption does not prove a same-page shared table.
    marker = caption_table_marker(text)
    if (
        marker is None
        or table_marker_identity(marker.group()).casefold() != table_id.casefold()
    ):
        return False
    term = re.compile(
        r"\(?\b(?:continued|cont\.?|cont['’]d)\b\)?|续表|（续）|\(续\)", re.IGNORECASE
    )
    if continued and not term.search(text):
        return False
    clean = term.sub("", text).strip(" .:：-()（）")
    original = original_context(original_caption).strip(" .:：-()（）")
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
