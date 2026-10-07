"""One cell-owned adapter using the existing grid, OCR and biology authorities."""

from __future__ import annotations

import re
from dataclasses import replace

from .activity_grid_cells import cell_text, crosses_cell, validate_grid
from .activity_header_metrics import distinct_value_keys, normalize_metric_text
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
        has_context = bool(
            ACTIVITY_CONTEXT.search(text) or METRIC.search(normalize_metric_text(text))
        )
        has_rows = bool(
            re.search(
                r"(?:Compound|Cpd|Example|化合物|实施例)\s*[-:]?\s*\d+|[A-Za-z]-\d+\s+[A-G]",
                text,
                re.IGNORECASE,
            )
        )
        if (
            not text_map
            or (has_context and (TABLE_MARKER.search(text) or has_rows))
            or previous == page - 1
            and has_rows
            and has_context
        ):
            selected.append(page)
            previous = page
    return selected


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
    return text


def _read_cell(page, tokens: list[dict], bounds, *, identifier: bool, native: bool):
    raw = cell_text(tokens, bounds)
    crossing = crosses_cell(tokens, bounds)
    if identifier:
        value = normalize_compound(raw)
        kind = (
            "label"
            if re.match(r"Compound|Example|Cpd|Cmpd|实施例|化合物", raw, re.IGNORECASE)
            else "id"
        )
    else:
        value = normalize_value(raw)
        kind = (
            "plus"
            if re.fullmatch(r"\+{1,3}", value)
            else (
                "letter" if re.fullmatch(r"[A-D]", value, re.IGNORECASE) else "number"
            )
        )
    if native:
        # Shared lexical kinds do not support all printed suffixes, missing
        # markers or ranges. Original native tokens remain exact evidence.
        observations = [{"method": "native_cell", "text": raw}]
        return (
            value,
            observations,
            crossing or not bool(value if identifier else is_value(value)),
        )
    reading = read_cell(page, bounds, tokens, kind, False)
    refined = (
        normalize_compound(reading.value)
        if identifier
        else normalize_value(reading.value)
    )
    observations = list(reading.observations)
    if not any(o.get("text") == raw for o in observations):
        observations.insert(0, {"method": "page_ocr_cell", "text": raw})
    # Shared scalar OCR cannot erase comparators, classes, units or missing
    # markers. Conflicting reads retain the raw cell and require review.
    conflict = bool(
        value and refined and re.sub(r"\s+", "", value) != re.sub(r"\s+", "", refined)
    )
    review = crossing or conflict or reading.needs_review or not reading.value
    return value or refined, observations, review


def parse_grid(
    page, page_no: int, tokens: list[dict], region: dict, schema: GridSchema
) -> list[ActivityRow]:
    validate_grid(region, schema)
    xs, ys = region["xs"], region["ys"]
    native = bool(page.get_text("words"))
    output = []
    column_groups = [
        (
            (group.id_column, "compound_id"),
            *zip(
                (col for col, _ in group.value_columns),
                distinct_value_keys([key for _, key in group.value_columns]),
            ),
        )
        for group in schema.groups
    ]
    for row_index in range(schema.first_data_row, len(ys) - 1):
        for pair, columns in enumerate(column_groups):
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
                        "physical_column": column,
                        "raw_header": schema.raw_headers[column]
                        if schema.raw_headers
                        else "",
                        "bbox": list(bounds),
                        "observations": observations,
                    }
                )
                review |= (
                    withheld
                    or "unknown" in key.lower()
                    or key.startswith("compound_id [")
                )
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
                "raw_caption": context.raw_caption,
                "body_text": context.body_text,
                "raw_context": context.raw_context,
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
    biology_header_hints: dict[str, tuple[str, ...]] = {}
    generic_regions = []
    carry: tuple[GridSchema | BiologySchema, list[float], int] | None = None
    seeds = {page for page in pages if type(page) is int and 0 <= page < len(doc)}
    # A continuation need not repeat an assay keyword and may be absent from
    # classification. Inspect only a seed or the immediately following page
    # of a proven table; gaps/mismatched grids terminate the chain below.
    for page_index in range(min(seeds, default=len(doc)), len(doc)):
        if page_index not in seeds and not (carry and carry[2] + 1 == page_index):
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
            context = context_from_text(prefix, prefix)
            schema: GridSchema | BiologySchema | None = grid_schema(context, matrix)
            # The existing biology authority owns its supported ratio/grade
            # schemas. It never competes with the generic scalar-header reader.
            if isinstance(schema, GridSchema):
                header = " ".join(schema.raw_headers)
            normalized_header = normalize_metric_text(header)
            metrics = list(METRIC.finditer(normalized_header))
            categorical = metrics and all(
                re.fullmatch(
                    r"(?:Ratio|Grade)(?:\s+(?:grade|class))?",
                    m.group().strip(),
                    re.IGNORECASE,
                )
                for m in metrics
            )
            biology_header = re.search(
                r"\b(?:degradation|anti[-\s]?proliferation)\b",
                normalized_header,
                re.IGNORECASE,
            )
            explicit_unknown = re.search(
                r"\bunknown\b|\?", normalized_header, re.IGNORECASE
            )
            if schema is None or (
                not explicit_unknown and (categorical or not metrics and biology_header)
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
                biology_header_hints.setdefault(table_id, schema.keys)
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
    for table_id, hints in biology_header_hints.items():
        # The biology authority owns the resolved experiment context. Do not
        # publish a generic discovery hint beside cell-line-specific row keys.
        observed = dict.fromkeys(
            key
            for record in records
            if record.table_id == table_id
            for key in record.values
        )
        result.headers.extend(observed or hints)
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
