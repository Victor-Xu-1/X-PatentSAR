"""Pure declared-header row reader shared by extraction and revalidation."""

from __future__ import annotations

import re

from .activity_headers import (
    ACTIVITY_CONTEXT,
    METRIC,
    context_from_text,
    infer_value_keys,
    normalize_metric_text,
)
from .activity_identity import (
    CONTROL,
    LABEL_PREFIX,
    PRINTED_ID,
    is_value,
    normalize_compound,
    normalize_value,
    value_tokens,
)
from .activity_metadata import metadata_role
from .activity_models import ActivityRow
from .activity_text_evidence import text_evidence
from .activity_text_legend import matching_legend, read_legend
from .source_section_roles import section_heading

_ROW = re.compile(
    rf"^((?:{LABEL_PREFIX})?{PRINTED_ID}|{CONTROL.pattern})(?=\s|\||$)\s*(.*)$",
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
    r"\bNo\.(?=\s|\||$)|\bID\b|\b[A-Za-z]-#",
    re.IGNORECASE,
)
_STOP = re.compile(
    r"^(?:\*|NA:|N/A:|Note:|以上数据|实验目的|实验方法|计算公式|权利要求|"
    r"What\s+is\s+claimed|EQUIVALENTS|\[\d{4,}\])",
    re.IGNORECASE,
)


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
        # An actual ID-column header establishes its role before a target or
        # cell name with digits can be mistaken for a compound-row identifier.
        start = _HEADER_START.search(line)
        if start:
            parts.append(line[start.start() :].strip())
            continue
        # A split original metric header can now also have an alphanumeric ID
        # shape. Establish its declared column role before interpreting rows.
        if parts and METRIC.fullmatch(normalize_metric_text(line.strip())):
            parts.append(line.strip())
            continue
        if _ROW.match(line.strip()):
            first_row = index
            break
        if parts and (
            METRIC.search(normalize_metric_text(line)) or metadata_role(line)
        ):
            parts.append(line.strip())
    return " ".join(parts), first_row


def parse_segment(
    caption: str,
    segment: str,
    *,
    page_no: int = 0,
    header: str = "",
    legend: tuple[str, dict[str, str]] | None = None,
    legend_issues: tuple[str, ...] = (),
) -> list[ActivityRow]:
    """Read one declared table. Never consult its number to infer a schema."""
    marker = re.search(r"\[\[PAGE\s+(\d+)\]\]", segment)
    if marker and page_no == 0:
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
    original_legend, issues = read_legend(segment, header)
    issues = list(dict.fromkeys([*issues, *legend_issues]))
    legend = matching_legend(original_legend or legend, header) if not issues else None
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
    metadata_headers = {}
    if re.search(r"\t|\|", header):
        columns = re.split(r"\t|\|", header.strip("|"))[1:]
        metadata_headers = {
            index: (raw, kind)
            for index, raw in enumerate(columns)
            if (kind := metadata_role(raw))
        }
    unpositioned_metadata = not re.search(r"\t|\|", header) and any(
        metadata_role(line) for line in lines[:first_row]
    )
    rows = []
    for row_index, line in enumerate(lines[first_row:], start=first_row):
        if _STOP.match(line.strip()):
            break
        if section_heading(line.strip()):
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
        measured = [
            index for index in range(len(keys)) if index not in metadata_headers
        ]
        review = (
            bool(issues)
            or ambiguous
            or any(not is_value(raw_values[index]) for index in measured)
        )
        review |= unpositioned_metadata or any(
            "unknown" in keys[index].lower() for index in measured
        )
        evidence = text_evidence(
            context,
            page_no,
            row_index,
            label,
            keys,
            values,
            line,
            header,
            metadata_headers,
        )
        review |= any(
            c.get("metadata_status") == "unresolved" for c in evidence["cells"]
        )
        if legend:
            evidence["legend"] = dict(legend[1])
        if issues:
            evidence["legend_issues"] = issues
        rows.append(
            ActivityRow(
                cpd=compound,
                activity_values={keys[index]: values[index] for index in measured},
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
