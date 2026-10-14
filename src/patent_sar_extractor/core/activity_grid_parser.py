"""Read every value through the single physical-cell evidence authority."""

from .activity_grid_cells import read_activity_cell, validate_grid
from .activity_header_metrics import distinct_value_keys
from .activity_metadata import mark_metadata, metadata_field
from .activity_models import ActivityRow, GridSchema
from .source_geometry import token_geometry_space


def parse_grid(
    page,
    page_no: int,
    tokens: list[dict],
    region: dict,
    schema: GridSchema,
    *,
    unresolved_rows: list[dict] | None = None,
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
            *[(col, metadata_field(kind)) for col, kind in group.metadata_columns],
        )
        for group in schema.groups
    ]
    for row_index in range(schema.first_data_row, len(ys) - 1):
        for pair, columns in enumerate(column_groups):
            metadata = dict(schema.groups[pair].metadata_columns)
            cells, values = [], {}
            review = (schema.header_resolution or {}).get("status") == "unresolved"
            compound = ""
            for column, key in columns:
                bounds = (xs[column], ys[row_index], xs[column + 1], ys[row_index + 1])
                value, observations, withheld = read_activity_cell(
                    page, tokens, bounds, identifier=key == "compound_id", native=native
                )
                cell = {
                    "field": key,
                    "value": value,
                    "physical_column": column,
                    "raw_header": schema.raw_headers[column]
                    if schema.raw_headers
                    else "",
                    "bbox": list(bounds),
                    "observations": observations,
                }
                if column in metadata:
                    cell = mark_metadata(cell, metadata[column])
                    if not value.strip() and cell["metadata_status"] == "missing":
                        withheld = (
                            False  # Proved original metadata blank, never potency.
                        )
                    withheld |= cell["metadata_status"] == "unresolved"
                cells.append(cell)
                review |= (
                    withheld
                    or "unknown" in key.lower()
                    or key.startswith("compound_id [")
                )
                if key == "compound_id":
                    compound = value
                elif column not in metadata:
                    values[key] = value
            if not compound:
                if any(
                    cell["value"] or any(o["text"] for o in cell["observations"])
                    for cell in cells
                ):
                    if unresolved_rows is not None:
                        unresolved_rows.append(
                            {
                                "page_no": page_no,
                                "table_id": schema.context.table_id,
                                "row": row_index,
                                "pair": pair,
                                "cells": cells,
                                "bbox": [
                                    min(c["bbox"][0] for c in cells),
                                    ys[row_index],
                                    max(c["bbox"][2] for c in cells),
                                    ys[row_index + 1],
                                ],
                                "reason": "unresolved_compound_id",
                            }
                        )
                        continue
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
                "geometry_space": token_geometry_space(tokens, native),
                "header_region": (
                    {
                        "page_no": schema.header_region[0],
                        "bbox": list(schema.header_region[1]),
                    }
                    if schema.header_region
                    else None
                ),
            }
            if schema.header_resolution is not None:
                evidence["header_resolution"] = schema.header_resolution
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
