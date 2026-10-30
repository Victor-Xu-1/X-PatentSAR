"""Exact table-caption claims shared by physical nomination and readback."""

import re

from .activity_header_sources import context_source_parts, source_context_region
from .cell_frame_proof import inside_box
from .source_cell_tokens import cell_tokens
from .source_observations import source_claim_runs
from .source_table_markers import caption_table_marker, table_marker_identity


def caption_claim(text):
    """Ignore only the table marker's separator, never a word/number difference."""
    marker = caption_table_marker(text)
    if marker is None:
        return None
    return (
        tuple(text[: marker.start()].split()),
        re.sub(r"\s+", "", table_marker_identity(marker.group())).upper(),
        tuple(text[marker.end() :].lstrip(" .:：\t\r\n").split()),
    )


def same_caption_claim(first, second):
    if not isinstance(first, str) or not isinstance(second, str):
        return False
    identity = caption_claim(first)
    return identity is not None and identity == caption_claim(second)


def original_caption_tokens(line, region):
    """A complete literal row inside one already-registered source context."""
    layout = region.get("layout") or region.get("transposed_layout") or {}
    snapshot = layout.get("original_source") or layout.get("context_sources")
    caption = (layout.get("context") or {}).get("raw_caption", "")
    if not snapshot or not same_caption_claim(caption, line["text"]):
        return None
    axes = region["grid_axes"]
    xs, ys = axes["xs"], axes["ys"]
    start = layout.get("data_start", layout.get("header_row", -1) + 1)
    if start <= 0 or start >= len(ys):
        return None
    scoped = source_context_region(snapshot, [xs[0], ys[0], xs[-1], ys[start]])
    if scoped is None:
        return None
    packet = snapshot["prefix"]
    parts = context_source_parts(packet, scoped)
    if parts is None:
        return None
    tokens = cell_tokens([token for part in parts for token in part], line["bbox"])
    if (
        not tokens
        or not same_caption_claim(
            " ".join(token["text"] for token in tokens), line["text"]
        )
        or source_claim_runs(packet, tokens=tokens)
        != (tuple(token["text"] for token in tokens),)
    ):
        return None
    return tokens


def caption_nomination_bounds(line, regions, page_size):
    """Unify overlapping OCR location proposals BEFORE complete original reads.

    OCR boxes are locators, not exact glyph extents. Only one existing caption's
    complete literal source row may enlarge a located proposal. No tolerance,
    nearest-row choice, missing word, table-ID repair or post-read geometry edit.
    """
    claims = []
    for region in regions:
        if region.get("kind") != "grid" or "grid_axes" not in region:
            continue
        tokens = original_caption_tokens(line, region)
        if tokens is None:
            continue
        boxes = [line["bbox"], *(token["bbox"] for token in tokens)]
        bounds = [
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        ]
        if inside_box(bounds, [0, 0, *page_size]) and bounds[3] <= region["bbox"][1]:
            claims.append(bounds)
    return claims[0] if len(claims) == 1 else list(line["bbox"])
