"""One declared-header reader for cached text/native unruled activity tables.

Whitespace alone cannot locate a missing middle cell. Such rows retain their
raw observations but withhold field assignment instead of shifting values.
"""

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
from .activity_identity import (
    CONTROL,
    ID_HEADER,
    LABEL_PREFIX,
    PRINTED_ID,
    is_value,
    normalize_compound,
    normalize_value,
    value_tokens,
)
from .activity_models import ActivityRow, ParsedActivity, TableContext

_ROW = re.compile(
    rf"^((?:{LABEL_PREFIX})?{PRINTED_ID}|{CONTROL.pattern})(?=\s|$)\s*(.*)$",
    re.IGNORECASE,
)
_PREFIXED_ROWS = re.compile(
    rf"(?<!\w){LABEL_PREFIX}{PRINTED_ID}(?=\s|$)", re.IGNORECASE
)
_SERIES_ROWS = re.compile(
    r"(?<![\w-])(?:[A-Za-z]{1,12}-\d+(?:-\d+)*|\d+-\d+)\s+[A-G](?=\s|$)", re.IGNORECASE
)
_HEADER_START = re.compile(
    r"(?:Compound|Cmpd|Cpd|Example)\s*(?:No\.?|ID|#)|化合物编号|实施例编号|"
    r"\bNo\.(?=\s|$)|\bID\b|\b[A-Za-z]-#",
    re.IGNORECASE,
)
_STOP = re.compile(
    r"^(?:\*|NA:|N/A:|Note:|以上数据|实验目的|实验方法|计算公式|权利要求|"
    r"What\s+is\s+claimed|EQUIVALENTS|\[\d{4,}\])",
    re.IGNORECASE,
)


def _caption_line(text: str) -> str:
    return next(
        (
            line.strip()
            for line in text.splitlines()
            if TABLE_MARKER.match(line.strip())
        ),
        "",
    )


def _legend(text: str) -> tuple[str, dict[str, str]] | None:
    source = normalize_metric_text(re.sub(r"\s+", " ", text))
    match = re.search(
        r"letter\s+codes?\s+for\s+(.{1,80}?)\s+include\s*:", source, re.IGNORECASE
    )
    if not match or not METRIC.search(match.group(1)):
        return None
    tail = source[match.end() : match.end() + 700]
    marker = TABLE_MARKER.search(tail)
    if marker:
        tail = tail[: marker.start()]
    definitions = {
        grade.upper(): definition.strip()
        for grade, definition in re.findall(
            r"\b([A-G])\s*\(\s*([^)]+)\)", tail, re.IGNORECASE
        )
    }
    return (match.group(1).strip(), definitions) if len(definitions) >= 2 else None


def _flat_lines(text: str) -> list[str]:
    """Only explicit printed label boundaries can split a flattened row stream."""
    starts = sorted(
        {
            m.start()
            for pattern in (_PREFIXED_ROWS, _SERIES_ROWS)
            for m in pattern.finditer(text)
        }
    )
    if not starts:
        return [text]
    result = [text[: starts[0]]]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        result.append(text[start:end])
    return result


def _find_header(lines: list[str]) -> tuple[str, int]:
    parts = []
    first_row = len(lines)
    for index, line in enumerate(lines):
        if _ROW.match(line.strip()):
            first_row = index
            break
        start = _HEADER_START.search(line)
        if start:
            parts.append(line[start.start() :].strip())
        elif parts and METRIC.search(normalize_metric_text(line)):
            parts.append(line.strip())
    return " ".join(parts), first_row


def _text_evidence(
    context: TableContext,
    page_no: int,
    row_index: int,
    label: str,
    keys: list[str],
    values: list[str],
    raw_row: str,
    raw_header: str,
) -> dict:
    return {
        "page_no": page_no,
        "table_id": context.table_id,
        "target": context.target,
        "assay": context.assay,
        "cell_line": context.cell_line,
        "row": row_index,
        "raw_header": raw_header[:10000],
        "cells": [
            {
                "field": "compound_id",
                "value": label,
                "bbox": None,
                "observations": [
                    {"method": "declared_text_row", "text": raw_row[:10000]}
                ],
            },
            *[
                {
                    "field": key,
                    "value": value,
                    "bbox": None,
                    "observations": [
                        {"method": "declared_text_cell", "text": raw_row[:10000]}
                    ],
                }
                for key, value in zip(keys, values)
            ],
        ],
    }


def parse_segment(
    caption: str,
    segment: str,
    *,
    page_no: int = 0,
    header: str = "",
    legend: tuple[str, dict[str, str]] | None = None,
) -> list[ActivityRow]:
    """Read one declared table. Never consult its number to infer a schema."""
    marker = re.search(r"\[\[PAGE\s+(\d+)\]\]", segment)
    if marker:
        page_no = int(marker.group(1))
    raw_lines = [line.rstrip() for line in segment.splitlines() if line.strip()]
    lines = []
    for line in raw_lines:
        if "[[PAGE" in line:
            continue
        # Flattened explicit Compound/Example rows are a single supported text
        # representation, not a second parser or numeric resynchronization path.
        lines.extend(_flat_lines(line))
    observed_header, first_row = _find_header(lines)
    header = observed_header or header
    legend = _legend(segment) or legend
    if not header and legend:
        header = legend[0]
    if not header or not (
        METRIC.search(normalize_metric_text(header)) or ACTIVITY_CONTEXT.search(caption)
    ):
        return []
    context = context_from_text(caption)
    metric_count = len(list(METRIC.finditer(normalize_metric_text(header))))
    # The legend itself is not another measurement column.
    if legend and metric_count == 0:
        metric_count = 1
    rows = []
    for row_index, line in enumerate(lines[first_row:], start=first_row):
        if _STOP.match(line.strip()):
            break
        matched = _ROW.match(line.strip())
        if not matched:
            continue
        label, tail = matched.groups()
        compound = normalize_compound(label)
        if not compound:
            continue
        positional = "\t" in line or "|" in line
        if positional:
            cells = re.split(r"\t|\|", line.strip("|"))
            values = [normalize_value(cell) for cell in cells[1:]]
        else:
            values = value_tokens(tail)
        if values is None:
            # Prose does not become a row merely because it contains numbers.
            continue
        expected = metric_count or len(values) or 1
        keys = infer_value_keys(caption, header, max(expected, len(values)))
        ambiguous = len(values) != expected and not positional
        if ambiguous:
            values = [""] * len(keys)
        elif len(values) < len(keys):
            values += [""] * (len(keys) - len(values))
        raw_values = list(values)
        if legend and len(keys) == 1:
            values = [legend[1].get(values[0].upper(), values[0])]
        review = ambiguous or any(not is_value(v) for v in raw_values)
        review |= any("unknown" in key.lower() for key in keys)
        evidence = _text_evidence(
            context, page_no, row_index, label, keys, values, line, header
        )
        if legend:
            evidence["legend"] = dict(legend[1])
        rows.append(
            ActivityRow(
                cpd=compound,
                activity_values=dict(zip(keys, values)),
                page_no=page_no,
                table_id=context.table_id,
                source="observed_text_table",
                confidence=0.5 if review else 0.9,
                needs_review=review,
                notes=(
                    "Unpositioned missing/extra cell; field assignments withheld. "
                    if ambiguous
                    else ""
                )
                + f"Declared text table; source label {label}.",
                activity_sources=[evidence],
            )
        )
    return rows


def _page_segments(text: str) -> list[tuple[str, str]]:
    # References in prose ("results in Table 3.") are not table captions.
    markers = list(
        re.finditer(
            r"(?m)^\s*(?:Table\s+[A-Za-z]?\d+[A-Za-z]?\b|表\s*\d+[A-Za-z]?)",
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
