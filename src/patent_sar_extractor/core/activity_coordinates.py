"""One cell-owned adapter using the existing grid, OCR and biology authorities."""

from __future__ import annotations

import re
from dataclasses import replace

from .activity_coverage import source_record
from .activity_grid_cells import continued_header_schema
from .activity_grid_context import _prefix, table_matrix
from .activity_grid_continuations import Panel, continued_panel
from .activity_grid_parser import parse_grid
from .activity_header_metrics import normalize_metric_text
from .activity_header_observation import refine_scanned_header
from .activity_header_roles import HeaderResolver
from .activity_headers import (
    METRIC,
    TABLE_MARKER,
    context_from_text,
    grid_schema,
)
from .activity_models import ActivityRow, GridSchema, ParsedActivity
from .activity_source_roles import method_page_evidence
from .activity_transposed import extract_transposed
from .biology_tables import BiologySchema, extract_tables, infer_schema
from .table_geometry import detect_ruled_table_regions, page_tokens


def coordinate_candidates(pages: list[int]) -> list[int]:
    """Every classified source gets geometry inspection before expensive OCR."""
    if not isinstance(pages, list) or any(
        type(page) is not int or not 0 <= page < 10000 for page in pages
    ):
        raise ValueError("Malformed activity coordinate seeds")
    return sorted(set(pages))


def extract_coordinate_tables(
    doc,
    pages: list[int],
    *,
    header_resolver: HeaderResolver | None = None,
    page_texts: dict[str, str] | None = None,
) -> ParsedActivity:
    """Recognized pages remain owned even if a table contains no data rows."""
    result = ParsedActivity()
    token_map = {}
    biology_grids: dict[int, list[dict]] = {}
    biology_header_hints: dict[str, tuple[str, ...]] = {}
    generic_regions = []
    panels: list[Panel] = []
    carry: tuple[GridSchema | BiologySchema, list[float], int] | None = None
    seeds = {page for page in pages if type(page) is int and 0 <= page < len(doc)}
    # A continuation need not repeat an assay keyword and may be absent from
    # classification. Inspect only a seed or the immediately following page
    # of a proven table; gaps/mismatched grids terminate the chain below.
    for page_index in range(min(seeds, default=len(doc)), len(doc)):
        if page_index not in seeds and not (
            carry
            and carry[2] + 1 == page_index
            or any(p.page + 1 == page_index for p in panels)
        ):
            continue
        panels = [p for p in panels if p.page >= page_index - 1]
        page = doc[page_index]
        regions = sorted(
            detect_ruled_table_regions(page, dpi=240),
            key=lambda r: (r["ys"][0], r["xs"][0]),
        )
        if not regions:
            native = page.get_text("text") if hasattr(page, "get_text") else ""
            observed = [
                text
                for text in (
                    native,
                    str((page_texts or {}).get(str(page_index), "") or ""),
                )
                if text.strip()
            ]
            proofs = [method_page_evidence(text) for text in observed]
            method = proofs[0] if proofs and all(proofs) else ""
            if method:
                result.coverage.append(
                    source_record(
                        page_index + 1,
                        "page",
                        None,
                        "",
                        method,
                        "context",
                        "observed_methods",
                        0,
                    )
                )
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
            transposed = extract_transposed(
                page, page_index + 1, tokens, region, matrix, context
            )
            if transposed is not None:
                result.owned_pages.update(transposed.owned_pages)
                result.rows.extend(transposed.rows)
                result.headers.extend(transposed.headers)
                result.coverage.extend(transposed.coverage)
                result.tables.extend(transposed.tables)
                carry = None
                continue
            schema: GridSchema | BiologySchema | None = grid_schema(context, matrix)
            if schema is None or isinstance(schema, GridSchema):
                schema = refine_scanned_header(page, region, schema)
                if schema is not None:
                    context = schema.context
            # The existing biology authority owns its supported ratio/grade
            # schemas. It never competes with the generic scalar-header reader.
            if isinstance(schema, GridSchema):
                if (
                    carry
                    and isinstance(carry[0], GridSchema)
                    and carry[2] + 1 == page_index
                    and region["ys"][0] < 130
                ):
                    schema = continued_header_schema(
                        carry[0], schema, carry[1], region["xs"], prefix
                    )
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
            if schema is None:
                schema = continued_panel(panels, page_index, region, context, prefix)
            if (
                schema is None
                and not new_caption
                and carry
                and isinstance(carry[0], BiologySchema)
                and region["ys"][0] < 130
            ):
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
            if schema is None and header_resolver is not None and page_index in seeds:
                schema = header_resolver(context, matrix, region, page_index + 1)
            if schema is None:
                result.coverage.append(
                    source_record(
                        page_index + 1,
                        "grid",
                        [
                            region["xs"][0],
                            region["ys"][0],
                            region["xs"][-1],
                            region["ys"][-1],
                        ],
                        context.table_id,
                        header,
                        "unresolved",
                        "unsupported_header",
                        0,
                    )
                )
                carry = None
                continue
            result.owned_pages.add(page_index)
            if isinstance(schema, BiologySchema):
                biology_grids.setdefault(page_index, []).append(region)
                table_id = schema.table_id
                biology_header_hints.setdefault(table_id, schema.keys)
            else:
                if schema.header_region is None and schema.first_data_row > 0:
                    schema = replace(
                        schema,
                        header_region=(
                            page_index + 1,
                            (
                                region["xs"][0],
                                region["ys"][0],
                                region["xs"][-1],
                                region["ys"][schema.first_data_row],
                            ),
                        ),
                    )
                generic_regions.append((page_index, region, schema))
                panels.append(Panel(page_index, region, schema))
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
    for page_index, regions in biology_grids.items():
        for region in regions:
            count = sum(
                record.page_no == page_index + 1
                and any(
                    isinstance(cell.get("bbox"), (list, tuple))
                    and region["xs"][0] <= cell["bbox"][0] < region["xs"][-1]
                    and region["ys"][0] <= cell["bbox"][1] < region["ys"][-1]
                    for cell in record.evidence.get("cells", [])
                )
                for record in records
            )
            result.coverage.append(
                source_record(
                    page_index + 1,
                    "grid",
                    [
                        region["xs"][0],
                        region["ys"][0],
                        region["xs"][-1],
                        region["ys"][-1],
                    ],
                    "",
                    "",
                    "parsed" if count else "unresolved",
                    "original_cells" if count else "no_original_rows",
                    count,
                )
            )
    for page_index, region, schema in generic_regions:
        unresolved = []
        rows = parse_grid(
            doc[page_index],
            page_index + 1,
            token_map[page_index],
            region,
            schema,
            unresolved_rows=unresolved,
        )
        result.unresolved_rows.extend(unresolved)
        result.coverage.extend(
            source_record(
                page_index + 1,
                "grid",
                item["bbox"],
                schema.context.table_id,
                "Unresolved original compound ID",
                "unresolved",
                "no_original_rows",
                0,
            )
            for item in unresolved
        )
        result.rows.extend(rows)
        result.coverage.append(
            source_record(
                page_index + 1,
                "grid",
                [region["xs"][0], region["ys"][0], region["xs"][-1], region["ys"][-1]],
                schema.context.table_id,
                " ".join(schema.raw_headers),
                "parsed" if rows else "unresolved",
                "original_cells" if rows else "no_original_rows",
                len(rows),
            )
        )
    result.coverage.sort(
        key=lambda item: (item["page_no"], (item["bbox"] or [0, 0])[1])
    )
    return result
