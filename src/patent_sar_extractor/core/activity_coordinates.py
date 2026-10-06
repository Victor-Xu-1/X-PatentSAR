"""One cell-owned adapter using the existing grid, OCR and biology authorities."""

from __future__ import annotations

import re
from dataclasses import replace

from .activity_headers import (
    ACTIVITY_CONTEXT,
    METRIC,
    TABLE_MARKER,
    context_from_text,
    grid_schema,
)
from .activity_identity import is_value, normalize_compound, normalize_value
from .activity_models import ActivityRow, GridSchema, ParsedActivity
from .biology_tables import BiologySchema, extract_tables, infer_schema
from .table_cells import read_cell
from .table_geometry import detect_ruled_table_regions, page_tokens


def coordinate_candidates(
    pages: list[int], text_map: dict[str, str] | None = None
) -> list[int]:
    """Cached table evidence gates expensive OCR; units in synthesis are not proof."""
    selected = []
    previous = None
    for page in sorted(set(pages)):
        text = str((text_map or {}).get(str(page), "") or "")
        has_context = bool(ACTIVITY_CONTEXT.search(text) or METRIC.search(text))
        has_rows = bool(
            re.search(
                r"(?:Compound|Cpd|Example|化合物|实施例)\s*[-:]?\s*\d+|[A-Za-z]-\d+\s+[A-G]",
                text,
                re.I,
            )
        )
        if not text_map or (has_context and (TABLE_MARKER.search(text) or has_rows)):
            selected.append(page)
            previous = page
        elif previous == page - 1 and has_rows and has_context:
            selected.append(page)
            previous = page
    return selected


def cell_text(tokens: list[dict], bounds: tuple[float, float, float, float]) -> str:
    x0, y0, x1, y1 = bounds
    owned = [t for t in tokens if x0 + 0.5 < t["x"] < x1 - 0.5 and y0 < t["y"] < y1]
    return " ".join(
        t["text"] for t in sorted(owned, key=lambda t: (round(t["y"] / 3), t["x"]))
    )


def table_matrix(tokens: list[dict], region: dict) -> list[list[str]]:
    xs, ys = region["xs"], region["ys"]
    return [
        [
            cell_text(tokens, (xs[i], ys[j], xs[i + 1], ys[j + 1]))
            for i in range(len(xs) - 1)
        ]
        for j in range(len(ys) - 1)
    ]


def _prefix(tokens: list[dict], region: dict) -> str:
    top = region["ys"][0]
    selected = [t for t in tokens if max(0, top - 310) <= t["y"] < top]
    lines: dict[int, list[dict]] = {}
    for token in selected:
        lines.setdefault(round(token["y"] / 3), []).append(token)
    text = "\n".join(
        " ".join(t["text"] for t in sorted(row, key=lambda t: t["x"]))
        for _, row in sorted(lines.items())
    )
    markers = list(TABLE_MARKER.finditer(text))
    if markers:
        # A new caption never borrows a previous table's assay.
        text = text[markers[-1].start() :]
    return text


def _read_cell(page, tokens: list[dict], bounds, *, identifier: bool, native: bool):
    raw = cell_text(tokens, bounds)
    if identifier:
        value = normalize_compound(raw)
        kind = (
            "label"
            if re.match(r"Compound|Example|Cpd|Cmpd|实施例|化合物", raw, re.I)
            else "id"
        )
    else:
        value = normalize_value(raw)
        kind = (
            "plus"
            if re.fullmatch(r"\+{1,3}", value)
            else ("letter" if re.fullmatch(r"[A-D]", value, re.I) else "number")
        )
    if native:
        # Shared lexical kinds do not support all printed suffixes, missing
        # markers or ranges. Original native tokens remain exact evidence.
        observations = [{"method": "native_cell", "text": raw}]
        return value, observations, not bool(value if identifier else is_value(value))
    reading = read_cell(page, bounds, tokens, kind, False)
    if identifier:
        value = normalize_compound(reading.value) or value
    else:
        value = reading.value or value
    # Unsupported scanned labels/ranges are retained but never auto-accepted.
    review = reading.needs_review or not reading.value
    return value, reading.observations, review


def parse_grid(
    page, page_no: int, tokens: list[dict], region: dict, schema: GridSchema
) -> list[ActivityRow]:
    xs, ys = region["xs"], region["ys"]
    native = bool(page.get_text("words"))
    output = []
    for row_index in range(schema.first_data_row, len(ys) - 1):
        for pair, group in enumerate(schema.groups):
            columns = ((group.id_column, "compound_id"), *group.value_columns)
            cells, values, review = [], {}, False
            compound = ""
            for column, key in columns:
                bounds = (xs[column], ys[row_index], xs[column + 1], ys[row_index + 1])
                value, observations, withheld = _read_cell(
                    page, tokens, bounds, identifier=key == "compound_id", native=native
                )
                cells.append(
                    {
                        "field": key,
                        "value": value,
                        "bbox": list(bounds),
                        "observations": observations,
                    }
                )
                review |= withheld or "unknown" in key.lower()
                if key == "compound_id":
                    compound = value
                else:
                    values[key] = value
            if not compound:
                if any(
                    cell["value"] or any(o["text"] for o in cell["observations"])
                    for cell in cells
                ):
                    raise RuntimeError(
                        f"Unresolved compound ID in {schema.context.table_id}, page {page_no}, row {row_index}"
                    )
                continue
            context = schema.context
            evidence = {
                "page_no": page_no,
                "table_id": context.table_id,
                "target": context.target,
                "assay": context.assay,
                "cell_line": context.cell_line,
                "row": row_index,
                "pair": pair,
                "cells": cells,
                "geometry_space": "unrotated" if native else "rendered",
            }
            output.append(
                ActivityRow(
                    cpd=compound,
                    activity_values=values,
                    page_no=page_no,
                    table_id=context.table_id,
                    source="observed_grid_cells",
                    confidence=0.5 if review else 0.95,
                    needs_review=review,
                    notes="Original cell ownership; unknown/conflicting cells withheld."
                    if review
                    else "Original cell ownership.",
                    activity_sources=[evidence],
                )
            )
    return output


def extract_coordinate_tables(doc, pages: list[int]) -> ParsedActivity:
    """Recognized pages remain owned even if a table contains no data rows."""
    result = ParsedActivity()
    token_map = {}
    biology_grids: dict[int, list[dict]] = {}
    generic_regions = []
    carry: tuple[GridSchema | BiologySchema, list[float], int] | None = None
    for page_index in sorted(set(pages)):
        if not 0 <= page_index < len(doc):
            continue
        page = doc[page_index]
        regions = sorted(
            detect_ruled_table_regions(page, dpi=240), key=lambda r: r["ys"][0]
        )
        if not regions:
            carry = None
            continue
        # No persistent page-number-only cache: different PDFs cannot borrow tokens.
        tokens = page_tokens(page)
        token_map[page_index] = tokens
        for region in regions:
            matrix = table_matrix(tokens, region)
            prefix = _prefix(tokens, region)
            header = " ".join(matrix[0]) if matrix else ""
            context = context_from_text(
                prefix.splitlines()[-1] if prefix else "", prefix
            )
            schema: GridSchema | BiologySchema | None = grid_schema(context, matrix)
            # The existing biology authority owns its supported ratio/grade
            # schemas. It never competes with the generic scalar-header reader.
            if not METRIC.search(header) or re.search(
                r"\bRatio\b.*\bGrade\b|degradation", header, re.I
            ):
                schema = (
                    infer_schema(f"{prefix} {header}", len(region["xs"]) - 1) or schema
                )
            new_caption = bool(TABLE_MARKER.search(prefix))
            if schema is None and not new_caption and carry and region["ys"][0] < 130:
                old, old_xs, old_page = carry
                if (
                    page_index == old_page + 1
                    and len(old_xs) == len(region["xs"])
                    and all(abs(a - b) <= 4 for a, b in zip(old_xs, region["xs"]))
                ):
                    schema = (
                        replace(old, first_data_row=0)
                        if isinstance(old, GridSchema)
                        else old
                    )
            if schema is None:
                carry = None
                continue
            result.owned_pages.add(page_index)
            if isinstance(schema, BiologySchema):
                biology_grids.setdefault(page_index, []).append(region)
                table_id = schema.table_id
                result.headers.extend(schema.keys)
            else:
                generic_regions.append((page_index, region, schema))
                table_id = schema.context.table_id
                result.headers.extend(
                    key for group in schema.groups for _, key in group.value_columns
                )
            result.tables.append(
                {
                    "table_id": table_id,
                    "pages": [page_index],
                    "heading_page_idx": page_index,
                    "heading_text": prefix,
                }
            )
            carry = schema, region["xs"], page_index
    records = extract_tables(
        doc,
        sorted(biology_grids),
        tokens_for_page=lambda p: token_map[p.number],
        grids_for_page=lambda p: biology_grids[p.number],
    )
    result.rows.extend(
        ActivityRow(
            cpd=r.compound,
            activity_values=r.values,
            page_no=r.page_no,
            table_id=r.table_id,
            source="ocr_biology_cells",
            confidence=0.5 if r.needs_review else 0.95,
            needs_review=r.needs_review,
            notes=r.notes,
            activity_sources=[r.evidence],
        )
        for r in records
    )
    for page_index, region, schema in generic_regions:
        result.rows.extend(
            parse_grid(
                doc[page_index], page_index + 1, token_map[page_index], region, schema
            )
        )
    return result
