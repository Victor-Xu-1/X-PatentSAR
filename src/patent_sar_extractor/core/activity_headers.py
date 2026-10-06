"""Interpret observed headers in printed order, with explicit unknowns."""

from __future__ import annotations

import re

from .activity_identity import ID_HEADER, is_id_header
from .activity_models import ColumnGroup, GridSchema, TableContext

TABLE_MARKER = re.compile(r"\bTable\s+[A-Za-z]?\d+[A-Za-z]?\b|表\s*\d+[A-Za-z]?", re.I)
METRIC = re.compile(
    r"(?<![A-Za-z0-9])(?:p?IC50|EC50|DC50|GI50|CC50|Ki|Kd|Imax|Dmax|"
    r"Ymin|Ymax|Clint|CL|t1/2|Cmax|AUC(?:0?(?:-|–)?(?:t|inf))?|TGI|"
    r"Dose|Tumou?r\s+volume|p\s*value|Ratio|Grade|F)(?![A-Za-z0-9])"
    r"\s*(?:\([^)]*\)|（[^）]*）)?(?:\s+(?:grade|class))?",
    re.I,
)
ACTIVITY_CONTEXT = re.compile(
    r"assay|activity|binding|degrad|prolifer|xenograft|microsom|pharmacokinetic|"
    r"活性|降解|增殖|药代|药效|抑制|代谢|HTRF|HiBiT|NanoBiT|FACS",
    re.I,
)
_UNITLESS = re.compile(r"^(?:p\s*value|Ratio|Grade|Ymin|Ymax)$", re.I)


def unknown_key(index: int) -> str:
    return f"Unknown activity field {index} (unit unknown)"


def normalize_metric_text(text: str) -> str:
    """Canonical spelling of a recognized metric; raw headers remain evidence."""
    return re.sub(r"\b(p?IC|EC|DC|GI|CC)5[oO]\b", r"\g<1>50", text, flags=re.I)


def _key(text: str, index: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip(" |:：;,.")
    clean = re.sub(r"\s*[（(]\s*", " (", clean)
    clean = clean.replace("）", ")")
    if not METRIC.search(clean):
        return unknown_key(index)
    match = METRIC.search(clean)
    metric = match.group().strip() if match else ""
    if not re.search(r"\([^)]*\)", metric) and not _UNITLESS.fullmatch(metric):
        clean += " (unit unknown)"
    return clean


def infer_value_keys(caption: str, header: str, value_count: int) -> list[str]:
    """Caption supplies provenance, not a hidden target/unit lookup table."""
    del caption
    # Remove only an anchored printed ID header, not biological context.
    clean = re.sub(r"\s+", " ", normalize_metric_text(str(header or ""))).strip()
    match = ID_HEADER.match(clean)
    if match and (match.end() == len(clean) or clean[match.end()] in " .:：|\t"):
        clean = clean[match.end() :].lstrip(" .:：|\t")
    keys = []
    end = 0
    for match in METRIC.finditer(clean):
        prefix = clean[end : match.start()].strip(" |:：;,.")
        if is_id_header(prefix):
            prefix = ""
        label = f"{prefix} {match.group()}".strip()
        keys.append(_key(label, len(keys) + 1))
        end = match.end()
    while len(keys) < value_count:
        keys.append(unknown_key(len(keys) + 1))
    return keys[:value_count]


def context_from_text(caption: str, surrounding: str = "") -> TableContext:
    """Store local source language; scientific identity requires explicit labels."""
    caption = re.sub(r"\s+", " ", caption).strip()[:300]
    marker = TABLE_MARKER.search(caption)
    table_id = marker.group() if marker else ""
    raw_assay = TABLE_MARKER.sub("", caption, count=1).strip(" .:：")
    source = f"{surrounding}\n{caption}"
    target = re.search(r"(?:Target|靶点)\s*[:：]\s*([\w-]+)", source, re.I)
    assay = re.search(r"(?:Assay|实验)\s*[:：]\s*([^;\n]{1,120})", source, re.I)
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
    )


def grid_schema(context: TableContext, matrix: list[list[str]]) -> GridSchema | None:
    """Physical columns prove order and repeated ID/value groups."""
    if not matrix:
        return None
    for row_index, row in enumerate(matrix[:3]):
        identifiers = [i for i, cell in enumerate(row) if is_id_header(cell)]
        if not identifiers:
            continue
        groups = []
        for index, start in enumerate(identifiers):
            end = identifiers[index + 1] if index + 1 < len(identifiers) else len(row)
            columns = tuple(
                (column, infer_value_keys(context.caption, row[column], 1)[0])
                for column in range(start + 1, end)
            )
            if columns:
                groups.append(ColumnGroup(start, columns))
        if groups and (
            any(METRIC.search(cell) for cell in row)
            or ACTIVITY_CONTEXT.search(context.caption)
        ):
            return GridSchema(context, tuple(groups), row_index + 1)
    return None
