"""Transposed tables reuse the same bounded original header/context authority."""

from dataclasses import asdict

from .activity_header_sources import (
    capture_header_sources,
    header_source_conflicts,
    select_header_context,
)
from .activity_headers import context_from_text
from .activity_models import GridSchema, TableContext


def capture_transposed_context(page, tokens, region, header_row, context):
    """Retain the actual source window, never just an assay string on a row."""
    return {
        "context": asdict(context),
        "context_sources": capture_header_sources(page, region, header_row + 1, tokens),
    }


def transposed_context_matches(layout, axes):
    """Replay original claims without OCR; unknown/conflicting origins refuse."""
    context = TableContext(**layout["context"])
    if context.claim_conflicts:
        return False
    raw = context_from_text(context.raw_context, context.raw_context)
    if asdict(raw) != layout["context"]:
        return False
    xs, ys = axes["xs"], axes["ys"]
    row = layout["header_row"]
    band = [xs[0], ys[0], xs[-1], ys[row + 1]]
    # A compound header may sit under one or more literal merged assay rows.
    # Preserve all original header rows, not just the final compound-ID row.
    headers = tuple(
        " ".join(cell["text"] for cell in column[: row + 1] if cell["text"])
        for column in layout["columns"]
    )
    schema = GridSchema(context, (), row + 1, headers)
    snapshot = layout["context_sources"]
    flags = header_source_conflicts(snapshot, band, (), context.raw_context, schema)
    if flags is None or any(flags[0]) or flags[1]:
        return False
    selected = select_header_context(snapshot, band, raw)
    return selected is not None and asdict(selected) == layout["context"]
