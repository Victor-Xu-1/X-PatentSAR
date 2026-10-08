"""Interpret observed headers in printed order, with explicit unknowns."""

from __future__ import annotations

import re

from .activity_header_metrics import (
    METRIC,
    UNITLESS,
    distinct_value_keys,
    explicit_unit,
    normalize_metric_text,
)
from .activity_identity import ID_HEADER, is_id_header, is_value, normalize_value
from .activity_models import ColumnGroup, GridSchema, TableContext

TABLE_MARKER = re.compile(
    r"\bTable\s+[A-Za-z]?\d+[A-Za-z]?\b|表\s*\d+[A-Za-z]?", re.IGNORECASE
)
_CAPTION_LINE = re.compile(
    rf"^[ \t]*(?:\[\d{{4,8}}\][ \t]*)?(?:{TABLE_MARKER.pattern})",
    re.IGNORECASE | re.MULTILINE,
)
_PARAGRAPH_NUMBER = re.compile(r"^\[\d{4,8}\]\s*$")
ACTIVITY_CONTEXT = re.compile(
    r"assay|activity|binding|degrad|prolifer|xenograft|microsom|pharmacokinetic|"
    r"活性|降解|增殖|药代|药效|抑制|代谢|HTRF|HiBiT|NanoBiT|FACS",
    re.IGNORECASE,
)


def unknown_key(index: int) -> str:
    return f"Unknown activity field {index} (unit unknown)"


def _key(text: str, index: int) -> str:
    clean = re.sub(r"\s+", " ", normalize_metric_text(text)).strip(" |:：;,.")
    clean = re.sub(r"\s*[（(]\s*", " (", clean)
    clean = clean.replace("）", ")")
    matches = list(METRIC.finditer(clean))
    if len(matches) != 1:
        if not clean:
            return unknown_key(index)
        # Preserve explicit unknown labels/units, but never pick one of several
        # competing metric names within a single physical cell.
        unit = re.search(r"\s*\(([^()]*)\)$", clean) if not matches else None
        label = clean[: unit.start()].rstrip() if unit else clean
        return f"Unknown activity field {index}: {label} ({unit.group(1) if unit else 'unit unknown'})"
    metric = matches[0].group().strip()
    units = [
        (part, unit)
        for part in re.finditer(r"\(([^()]*)\)", clean)
        if (unit := explicit_unit(part.group(1)))
    ]
    if units and len({unit for _, unit in units}) == 1:
        part, unit = units[-1]
        # Context annotations remain in the label; a known literal unit stays
        # terminal for existing consumers, never transformed to another unit.
        clean = f"{(clean[: part.start()] + clean[part.end() :]).strip()} ({unit})"
    elif not units and (unit := explicit_unit(clean[matches[0].end() :])):
        clean = f"{clean[: matches[0].end()].rstrip()} ({unit})"
    elif not UNITLESS.fullmatch(metric.split("(")[0].strip()):
        clean += " (unit unknown)"
    return re.sub(r"\s+", " ", clean)


def infer_value_keys(caption: str, header: str, value_count: int) -> list[str]:
    """Caption supplies provenance, not a hidden target/unit lookup table."""
    del caption
    if value_count <= 0:
        return []
    # Explicit separators prove unknown/mixed column positions just like a grid.
    if re.search(r"\t|\|", str(header or "")):
        cells = re.split(r"\t|\|", str(header).strip("|"))
        if cells and is_id_header(cells[0]):
            cells = cells[1:]
        keys = [_key(cell, i + 1) for i, cell in enumerate(cells[:value_count])]
        keys.extend(unknown_key(i + 1) for i in range(len(keys), value_count))
        return distinct_value_keys(keys)
    # Remove only an anchored printed ID header, not biological context.
    clean = re.sub(r"\s+", " ", normalize_metric_text(str(header or ""))).strip()
    match = ID_HEADER.match(clean)
    if match and (match.end() == len(clean) or clean[match.end()] in " .:：|\t"):
        clean = clean[match.end() :].lstrip(" .:：|\t")
    matches = list(METRIC.finditer(clean))
    if value_count == 1:
        return [_key(clean, 1)]
    keys = []
    end = 0
    for match in matches:
        prefix = clean[end : match.start()].strip(" |:：;,.")
        if is_id_header(prefix):
            prefix = ""
        label = f"{prefix} {match.group()}".strip()
        keys.append(_key(label, len(keys) + 1))
        end = match.end()
    while len(keys) < value_count:
        keys.append(
            _key(clean, 1) if not keys and not matches else unknown_key(len(keys) + 1)
        )
    return distinct_value_keys(keys[:value_count])


def context_from_text(caption: str, surrounding: str = "") -> TableContext:
    """Store local source language; scientific identity requires explicit labels."""
    raw_context = str(surrounding or caption)
    raw_caption, body_text, source = _context_parts(str(caption), str(surrounding))
    caption = re.sub(r"^\[\d{4,8}\]\s*", "", raw_caption)
    caption = re.sub(r"\s+", " ", caption).strip()[:300]
    marker = TABLE_MARKER.search(caption)
    table_id = marker.group() if marker else ""
    raw_assay = TABLE_MARKER.sub("", caption, count=1).strip(" .:：")
    target = re.search(r"(?:Target|靶点)\s*[:：]\s*([\w-]+)", source, re.IGNORECASE)
    assay = re.search(
        r"(?:Assay|实验)\s*[:：]\s*([^;\n]{1,120})", source, re.IGNORECASE
    )
    cells = re.findall(
        r"\b([A-Za-z][A-Za-z0-9-]{1,20})\s+cells\b|([A-Za-z][A-Za-z0-9-]{1,20})细胞",
        source,
    )
    return TableContext(
        table_id=table_id,
        caption=caption,
        target=target.group(1) if target else None,
        assay=assay.group(1).strip() if assay else raw_assay or None,
        cell_line=next((a or b for a, b in reversed(cells)), None),
        raw_caption=raw_caption,
        body_text=body_text,
        raw_context=raw_context,
    )


def _context_parts(caption: str, surrounding: str) -> tuple[str, str, str]:
    """A line-anchored caption owns context; prose references are provenance only."""
    source = surrounding or caption
    markers = list(_CAPTION_LINE.finditer(source))
    if not markers and caption and caption != source:
        source = f"{caption}\n{source}"
        markers = list(_CAPTION_LINE.finditer(source))
    if markers:
        start = markers[-1].start()
        end = source.find("\n", markers[-1].end())
        if end < 0:
            end = len(source)
        raw_caption = source[start:end].strip()
        label = re.sub(r"^\[\d{4,8}\]\s*", "", raw_caption)
        if not TABLE_MARKER.sub("", label, count=1).strip(" .:：") and end < len(
            source
        ):
            title_end = source.find("\n", end + 1)
            if title_end < 0:
                title_end = len(source)
            title = source[end + 1 : title_end].strip()
            if (
                title
                and not re.match(
                    r"\[\d{4,8}\]|(?:Target|Assay|靶点|实验)\s*[:：]",
                    title,
                    re.IGNORECASE,
                )
                and not _CAPTION_LINE.match(title)
            ):
                end = title_end
                raw_caption = source[start:end].strip()
        body = source[end:].lstrip("\n")
        # Keep the whole observed window separately, but a new caption cannot
        # borrow a previous table's explicit target/assay labels.
        return raw_caption, body, source[start:]
    raw_caption = caption.strip()
    if _PARAGRAPH_NUMBER.fullmatch(raw_caption):
        raw_caption = ""
    body = surrounding if surrounding != raw_caption else ""
    return raw_caption, body, source


def grid_schema(
    context: TableContext,
    matrix: list[list[str]],
    *,
    identifier_columns: tuple[int, ...] | None = None,
) -> GridSchema | None:
    """Physical columns prove order and repeated ID/value groups."""
    if not matrix:
        return None
    if any(len(row) != len(matrix[0]) for row in matrix):
        raise ValueError("Activity grid has inconsistent physical column counts")
    for row_index, row in enumerate(matrix[:3]):
        identifiers = (
            list(identifier_columns)
            if identifier_columns is not None and row_index == 0
            else [i for i, cell in enumerate(row) if is_id_header(cell)]
        )
        if any(type(i) is not int or not 0 <= i < len(row) for i in identifiers) or len(
            set(identifiers)
        ) != len(identifiers):
            raise ValueError("Invalid original header roles")
        if not identifiers:
            continue
        first_data_row = row_index + 1
        header_rows = [row]
        for candidate in matrix[first_data_row:]:
            if not _header_continuation(header_rows, candidate, identifiers):
                break
            header_rows.append(candidate)
            first_data_row += 1
        raw_headers = tuple(
            "\n".join(parts[column] for parts in header_rows if parts[column])
            for column in range(len(row))
        )
        groups = []
        for index, start in enumerate(identifiers):
            end = identifiers[index + 1] if index + 1 < len(identifiers) else len(row)
            positions = list(range(start + 1, end))
            if len(identifiers) == 1:
                positions = [*range(start), *positions]
            elif identifiers[0] != 0:
                raise ValueError(
                    "Activity columns precede ambiguous repeated ID groups"
                )
            keys = distinct_value_keys(
                [_key(raw_headers[col], i + 1) for i, col in enumerate(positions)]
            )
            columns = tuple(zip(positions, keys))
            if columns:
                groups.append(ColumnGroup(start, columns))
        if groups and (
            any(METRIC.search(normalize_metric_text(cell)) for cell in raw_headers)
            or ACTIVITY_CONTEXT.search(context.caption)
        ):
            return GridSchema(context, tuple(groups), first_data_row, raw_headers)
    return None


def _header_continuation(
    headers: list[list[str]], row: list[str], ids: list[int]
) -> bool:
    """Stop before values or unproved missing-ID rows; never resynchronize data."""
    if any(row[col].strip() and not is_id_header(row[col]) for col in ids):
        return False
    columns = [col for col in range(len(row)) if col not in ids and row[col].strip()]
    if not columns or any(is_value(normalize_value(row[col])) for col in columns):
        return False
    if any(is_id_header(row[col]) for col in ids):
        return True
    metric_columns = [
        col for col in columns if METRIC.search(normalize_metric_text(row[col]))
    ]
    if metric_columns:
        return all(
            not METRIC.search(normalize_metric_text("\n".join(h[col] for h in headers)))
            for col in metric_columns
        )
    # Units may complete an already observed metric, but cannot swallow a data
    # row beneath a complete header simply because its ID is absent.
    return all(
        explicit_unit(row[col])
        and (
            previous := normalize_metric_text("\n".join(h[col] for h in headers))
        ).strip()
        and (METRIC.search(previous) or row[col].strip().startswith(("(", "（")))
        and not re.search(r"\([^()]*\)", previous)
        for col in columns
    )
