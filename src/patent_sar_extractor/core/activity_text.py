"""One text-table coordinator over the shared pure row reader."""

from __future__ import annotations

import re

from .activity_coverage import source_record
from .activity_headers import (
    ACTIVITY_CONTEXT,
    METRIC,
    TABLE_MARKER,
    context_from_text,
    infer_value_keys,
    normalize_metric_text,
)
from .activity_identity import ID_HEADER
from .activity_models import ParsedActivity
from .activity_text_rows import _HEADER_START, _find_header, _legend, parse_segment


def _page_segments(text: str) -> list[tuple[str, str]]:
    # References in prose ("results in Table 3.") are not table captions.
    markers = list(
        re.finditer(
            rf"(?m)^\s*(?:{TABLE_MARKER.pattern})",
            text,
            re.IGNORECASE,
        )
    )
    if not markers:
        # A flattened legend/caption is allowed only with a following printed
        # ID header, not an arbitrary "results in Table N" prose mention.
        markers = [
            m
            for m in TABLE_MARKER.finditer(text)
            if _HEADER_START.search(text[m.end() : m.end() + 250])
        ]
    if not markers:
        return [("", text)]
    result = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        segment = text[marker.start() : end]
        caption = segment.splitlines()[0].strip()
        # For a flattened paragraph the caption ends at the observed ID header.
        id_header = _HEADER_START.search(caption)
        if id_header:
            caption = caption[: id_header.start()].strip()
        result.append((caption, segment))
    return result


def extract_text_tables(pages: list[int], text_map: dict[str, str]) -> ParsedActivity:
    """Bounded continuation: adjacent supplied pages, no competing owned pages."""
    result = ParsedActivity()
    carry: tuple[str, str, tuple[str, dict[str, str]] | None, int] | None = None
    for page_index in sorted(set(pages)):
        text = str(text_map.get(str(page_index), "") or "")
        if not text.strip():
            carry = None
            continue
        for caption, segment in _page_segments(text):
            lines = [line for line in segment.splitlines() if line.strip()]
            observed_header, _ = _find_header(lines)
            legend = _legend(text)
            if caption:
                carry = None  # Every new table establishes its own context.
            elif carry and page_index == carry[3] + 1:
                caption = carry[0]
                observed_header = observed_header or carry[1]
                legend = legend or carry[2]
            elif not observed_header:
                carry = None
                continue
            rows = parse_segment(
                caption,
                segment,
                page_no=page_index + 1,
                header=observed_header,
                legend=legend,
            )
            recognized = bool(
                observed_header
                and ID_HEADER.search(observed_header)
                and (
                    METRIC.search(normalize_metric_text(observed_header))
                    or ACTIVITY_CONTEXT.search(caption)
                )
            )
            if rows or recognized:
                result.owned_pages.add(page_index)
                result.rows.extend(rows)
                context = context_from_text(caption)
                result.tables.append(
                    {
                        "table_id": context.table_id,
                        "pages": [page_index],
                        "heading_page_idx": page_index,
                        "heading_text": caption,
                    }
                )
                result.headers.extend(
                    infer_value_keys(
                        caption,
                        observed_header,
                        len(
                            list(
                                METRIC.finditer(normalize_metric_text(observed_header))
                            )
                        ),
                    )
                )
                carry = (caption, observed_header, legend, page_index)
                result.coverage.append(
                    source_record(
                        page_index + 1,
                        "text",
                        None,
                        context.table_id,
                        observed_header or caption,
                        "parsed" if rows else "unresolved",
                        "declared_text" if rows else "no_original_rows",
                        len(rows),
                    )
                )
            else:
                if observed_header or ACTIVITY_CONTEXT.search(caption):
                    context = context_from_text(caption)
                    result.coverage.append(
                        source_record(
                            page_index + 1,
                            "text",
                            None,
                            context.table_id,
                            observed_header or caption,
                            "unresolved",
                            "unsupported_header",
                            0,
                        )
                    )
                carry = None
    return result
