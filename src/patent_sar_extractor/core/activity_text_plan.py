"""One bounded original text-scope planner, shared by extraction and proof reads."""

import re

from .activity_continuation_policy import (
    canonical_header,
    continuation_prefix,
    continued_context_prefix,
)
from .activity_headers import (
    ACTIVITY_CONTEXT,
    ID_HEADER,
    METRIC,
    TABLE_MARKER,
    normalize_metric_text,
)
from .activity_identity import value_tokens
from .activity_source_discovery import _original_windows
from .activity_text_legend import read_legend
from .activity_text_partition import validate_barriers
from .activity_text_rows import (
    _HEADER_START,
    _ROW,
    _find_header,
    _flat_lines,
    declared_text_context,
    parse_segment,
)

MAX_TEXT_BYTES = 16 * 1024 * 1024


def validate_text_pages(pages):
    if (
        not isinstance(pages, dict)
        or len(pages) > 10000
        or any(
            not isinstance(key, str)
            or not re.fullmatch(r"[1-9]\d{0,3}|10000", key)
            or not isinstance(text, str)
            or len(text) > 100000
            for key, text in pages.items()
        )
    ):
        raise ValueError("Malformed original text observation inventory")
    if sum(len(text.encode()) for text in pages.values()) > MAX_TEXT_BYTES:
        raise ValueError("Original text observations exceed their bounded inventory")


def segments(text, *, barriers=()):
    """Reuse the original section/table authority, retaining physical text order."""
    validate_barriers(barriers, text)
    if barriers:
        cursor = 0
        for left, right in barriers:
            for start, end, caption, body in segments(text[cursor:left]):
                yield cursor + start, cursor + end, caption, body
            yield left, right, "", None
            cursor = right
        for start, end, caption, body in segments(text[cursor:]):
            yield cursor + start, cursor + end, caption, body
        return
    offset = 0
    for window in _original_windows(text, split_tables=False):
        markers = list(
            re.finditer(rf"(?m)^\s*{TABLE_MARKER.pattern}", window, re.IGNORECASE)
        )
        if not markers:
            markers = [
                m
                for m in TABLE_MARKER.finditer(window)
                if _HEADER_START.search(window[m.end() : m.end() + 250])
            ]
        starts = sorted({0, *[m.start() for m in markers]})
        legend_caption = None
        if len(starts) > 1 and starts[0] == 0:
            prefix = window[: starts[1]]
            legend, issues = read_legend(prefix)
            # A literal pre-table declaration belongs only to the immediately
            # following table in this original section. An independent header
            # or result row prevents attaching a preceding dataset to it.
            if (
                (legend or issues)
                and not _HEADER_START.search(prefix)
                and not any(
                    (match := _ROW.match(line.strip()))
                    and (
                        value_tokens(match.group(2)) is not None
                        or "|" in line
                        or "\t" in line
                    )
                    for line in canonical_lines(prefix)
                )
            ):
                legend_caption = starts[1]
                starts.pop(1)
        for start, end in zip(starts, [*starts[1:], len(window)]):
            body = window[start:end]
            title_source = (
                window[legend_caption:end]
                if start == 0 and legend_caption is not None
                else body
            )
            first = (
                title_source.splitlines()[0].strip()
                if title_source.splitlines()
                else ""
            )
            caption = first if TABLE_MARKER.match(first) else ""
            if caption and (header := _HEADER_START.search(caption)):
                caption = caption[: header.start()].strip()
            yield offset + start, offset + end, caption, body
        offset += len(window)


def canonical_lines(body):
    return [
        part
        for line in body.splitlines()
        if line.strip() and "[[PAGE" not in line
        for part in _flat_lines(line.rstrip())
    ]


def recognized(header, caption):
    return bool(
        header
        and ID_HEADER.search(header)
        and (
            METRIC.search(normalize_metric_text(header))
            or ACTIVITY_CONTEXT.search(caption)
        )
    )


def source_plan(pages, *, page_count=None, page_reader=None, page_barriers=None):
    """A source may inherit only from one closed immediately-adjacent table."""
    validate_text_pages(pages)
    if page_count is not None and (
        type(page_count) is not int or not 0 <= page_count <= 10000
    ):
        raise ValueError("Original text page count exceeds its bound")
    plan, previous = [], None
    maximum = page_count if page_count is not None else max(map(int, pages), default=0)
    if any(int(page) > maximum for page in pages):
        raise ValueError("Original text observation lies outside the document")
    total_bytes = sum(len(text.encode()) for text in pages.values())
    for page_no in range(min(map(int, pages), default=maximum + 1), maximum + 1):
        if str(page_no) not in pages:
            if (
                page_reader is None
                or not previous
                or not previous["closed"]
                or previous["key"][0] + 1 != page_no
            ):
                previous = None
                continue
            original = page_reader(page_no - 1)
            validate_text_pages({str(page_no): original})
            total_bytes += len(original.encode())
            if total_bytes > MAX_TEXT_BYTES:
                raise ValueError(
                    "Original text observations exceed their bounded inventory"
                )
            pages[str(page_no)] = original
        text = pages[str(page_no)]
        if not text.strip():
            previous = None
            continue
        for start, end, printed_caption, body in segments(
            text, barriers=(page_barriers or {}).get(str(page_no), ())
        ):
            if body is None:
                previous = None
                continue
            lines = canonical_lines(body)
            header, first_row = _find_header(lines)
            key = [page_no, start, end]
            leading = "\n".join(lines[:first_row])
            if header:
                pattern = r"\s+".join(re.escape(part) for part in header.split())
                leading = re.sub(pattern, "", leading, count=1)
            if printed_caption:
                leading = leading.replace(printed_caption, "")
            inherited = bool(
                previous
                and previous["key"][0] + 1 == page_no
                and start == 0
                and previous["closed"]
                and (
                    not header
                    or canonical_header(header) == canonical_header(previous["header"])
                )
                and (
                    continuation_prefix(leading)
                    if not printed_caption
                    else continued_context_prefix(
                        f"{printed_caption}\n{leading}", previous["context"]
                    )
                )
            )
            caption = previous["caption"] if inherited else printed_caption
            header = header or (previous["header"] if inherited else "")
            context = (
                previous["context"]
                if inherited
                else declared_text_context(caption, lines, first_row)
            )
            legend, issues = read_legend(body, header)
            if inherited and legend is None and not issues:
                legend, issues = previous["legend"], previous["legend_issues"]
            rows = parse_segment(
                caption,
                body,
                page_no=page_no,
                header=header,
                legend=legend,
                legend_issues=tuple(issues),
                context=context,
            )
            declared = recognized(header, caption)
            if not rows and not declared:
                if any(
                    (match := _ROW.match(line.strip()))
                    and (
                        value_tokens(match.group(2)) is not None
                        or "|" in line
                        or "\t" in line
                    )
                    for line in lines
                ) or ACTIVITY_CONTEXT.search(printed_caption):
                    plan.append(
                        {
                            "key": key,
                            "caption": caption,
                            "header": header,
                            "body": body,
                            "legend": None,
                            "legend_issues": [],
                            "rows": [],
                            "origin": key,
                            "parent": None,
                            "status": "unresolved",
                        }
                    )
                previous = None
                continue
            last = max((r.activity_sources[0]["row"] for r in rows), default=-1)
            trailer = "\n".join(lines[last + 1 :]) if last >= 0 else ""
            header_only = bool(
                not rows
                and declared
                and first_row == len(lines)
                and continuation_prefix(leading)
                and not issues
            )
            item = {
                "key": key,
                "context": context,
                "caption": caption,
                "header": header,
                "body": body,
                "legend": legend,
                "legend_issues": issues,
                "rows": rows,
                "origin": previous["origin"] if inherited else key,
                "parent": previous["key"] if inherited else None,
                "status": "parsed"
                if rows
                else "header"
                if header_only
                else "unresolved",
            }
            plan.append(item)
            previous = {
                **item,
                "closed": header_only or bool(rows and continuation_prefix(trailer)),
            }
    return plan


def scope_descriptor(item):
    return {"span": item["key"][1:], "origin": item["origin"], "parent": item["parent"]}


def validate_text_scope(record):
    scope = record.get("text_scope")
    if scope is None:
        return
    if (
        record["kind"] != "text"
        or not isinstance(scope, dict)
        or set(scope) != {"span", "origin", "parent"}
    ):
        raise ValueError("Malformed original text source scope")
    span = scope["span"]
    if (
        not isinstance(span, list)
        or len(span) != 2
        or any(type(v) is not int for v in span)
        or not 0 <= span[0] < span[1] <= 100000
    ):
        raise ValueError("Malformed original text source span")
    for key in ("origin", "parent"):
        anchor = scope[key]
        if anchor is None and key == "parent":
            continue
        if (
            not isinstance(anchor, list)
            or len(anchor) != 3
            or any(type(v) is not int for v in anchor)
            or not 1 <= anchor[0] <= record["page_no"]
            or not 0 <= anchor[1] < anchor[2] <= 100000
        ):
            raise ValueError("Malformed original text source origin")
