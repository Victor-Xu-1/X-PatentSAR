"""One cell-owned adapter using the existing grid, OCR and biology authorities."""

from __future__ import annotations

from dataclasses import replace

from .activity_context_geometry import context_region, grid_axes, grid_box
from .activity_coverage import source_record
from .activity_grid_context import _prefix, table_matrix
from .activity_grid_continuations import Panel, continued_panel
from .activity_grid_parser import parse_grid
from .activity_grid_role_observation import observe_characterization
from .activity_header_observation import refine_scanned_header
from .activity_header_roles import HeaderResolver
from .activity_headers import context_from_text, grid_schema
from .activity_models import GridSchema, ParsedActivity
from .activity_parallel_context import observe_parallel_context
from .activity_reference_observation import observe_result_references
from .activity_source_roles import method_page_evidence
from .activity_table_layout import prepare_layout
from .activity_transposed import extract_transposed
from .biology_tables import biology_grid_schema
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
    generic_regions = []
    panels: list[Panel] = []
    seeds = {page for page in pages if type(page) is int and 0 <= page < len(doc)}
    # A continuation need not repeat an assay keyword and may be absent from
    # classification. Inspect only a seed or the immediately following page
    # of a proven table; gaps/mismatched grids terminate the chain below.
    for page_index in range(min(seeds, default=len(doc)), len(doc)):
        if page_index not in seeds and not any(
            p.page + 1 == page_index for p in panels
        ):
            continue
        panels = [p for p in panels if p.page >= page_index - 1]
        page = doc[page_index]
        regions = sorted(
            detect_ruled_table_regions(page, dpi=240),
            key=lambda r: (r["ys"][0], r["xs"][0]),
        )
        native = page.get_text("text") if hasattr(page, "get_text") else ""
        observed = [
            text
            for text in (
                native,
                str((page_texts or {}).get(str(page_index), "") or ""),
            )
            if text.strip()
        ]
        result.coverage.extend(observe_result_references(page_index + 1, observed))
        if not regions:
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
            continue
        # No persistent page-number-only cache: different PDFs cannot borrow tokens.
        tokens = page_tokens(page)
        token_map[page_index] = tokens
        context_tables = [grid_box(region) for region in regions]
        for raw_region in regions:
            region = context_region(raw_region, context_tables)
            parallel_context = observe_parallel_context(page, region, tokens)
            if parallel_context is not None:
                region["parallel_context"] = parallel_context
            matrix = table_matrix(tokens, region)
            prefix = _prefix(tokens, region)
            header = " ".join(matrix[0]) if matrix else ""
            context = context_from_text(prefix, prefix)
            role_scope = observe_characterization(page, region, tokens, prefix)
            if role_scope is not None:
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
                        "non_activity",
                        "observed_characterization",
                        0,
                        role_scope=role_scope,
                        grid_axes=grid_axes(region),
                    )
                )
                continue
            transposed = extract_transposed(
                page, page_index + 1, tokens, region, matrix, context
            )
            if transposed is not None:
                result.owned_pages.update(transposed.owned_pages)
                result.rows.extend(transposed.rows)
                result.headers.extend(transposed.headers)
                result.coverage.extend(transposed.coverage)
                result.tables.extend(transposed.tables)
                continue
            schema = grid_schema(context, matrix)
            header_conflict = False
            if schema is None or isinstance(schema, GridSchema):
                header_observations = []
                schema = refine_scanned_header(
                    page,
                    region,
                    schema,
                    tokens=tokens,
                    evidence_sink=header_observations,
                )
                for proof in header_observations:
                    proof.update(
                        page_no=page_index + 1,
                        table_bbox=[
                            region["xs"][0],
                            region["ys"][0],
                            region["xs"][-1],
                            region["ys"][-1],
                        ],
                    )
                result.header_observations.extend(header_observations)
                header_conflict = any(
                    proof.get("conflicting_columns")
                    or proof.get("context_conflict")
                    or proof.get("reason") == "conflicting_identifier_columns"
                    for proof in header_observations
                )
                if schema is not None:
                    context = schema.context
            # Biological roles feed the same grid/continuation/cell authority.
            if schema is not None and not header_conflict:
                schema = biology_grid_schema(schema)
                schema = (
                    continued_panel(panels, page_index, region, context, prefix, schema)
                    or schema
                )
                header = " ".join(schema.raw_headers)
            if schema is None and not header_conflict:
                schema = continued_panel(
                    panels, page_index, region, context, prefix, matrix=matrix
                )
            if (
                schema is None
                and not header_conflict
                and header_resolver is not None
                and page_index in seeds
            ):
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
                        grid_axes=grid_axes(region),
                    )
                )
                continue
            result.owned_pages.add(page_index)
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
            schema = prepare_layout(
                schema, page_index + 1, region, tokens, prefix, regions
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
                parent_grid=grid_box(region),
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
                "parsed"
                if rows
                else "header"
                if schema.first_data_row == len(region["ys"]) - 1
                else "unresolved",
                "original_cells"
                if rows
                else "original_header_only"
                if schema.first_data_row == len(region["ys"]) - 1
                else "no_original_rows",
                len(rows),
                layout=schema.source_layout,
                grid_axes=grid_axes(region),
            )
        )
    result.coverage.sort(
        key=lambda item: (item["page_no"], (item["bbox"] or [0, 0])[1])
    )
    return result
