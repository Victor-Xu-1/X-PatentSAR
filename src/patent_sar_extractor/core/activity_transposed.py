"""Cell-owned activity tables with printed compounds across columns."""

from .activity_context_geometry import grid_axes
from .activity_coverage import source_record
from .activity_grid_cells import cell_text, read_activity_cell
from .activity_header_identity import header_conflict
from .activity_header_metrics import distinct_value_keys
from .activity_headers import _key
from .activity_metadata import mark_metadata, metadata_role
from .activity_models import ActivityRow, ParsedActivity
from .activity_transposed_source import (
    capture_transposed_layout,
    column_scope,
    declared_compound,
    transposed_header_row,
)
from .source_geometry import native_cell_text, token_geometry_space


def _merged_heading(tokens, region, row, column):
    xs, ys = region["xs"], region["ys"]
    rules = region.get("vertical_rules", [])

    def ruled(index):
        return any(
            abs(x - xs[index]) <= 4 and top <= ys[row] + 4 and bottom >= ys[row + 1] - 4
            for x, top, bottom in rules
        )

    left, right = column, column + 1
    while left > 0 and not ruled(left):
        left -= 1
    while right < len(xs) - 1 and not ruled(right):
        right += 1
    return cell_text(tokens, (xs[left], ys[row], xs[right], ys[row + 1]))


def extract_transposed(page, page_no, tokens, region, matrix, context):
    """Recognize orientation from literal IDs and metric rows, never value order."""
    header_row = transposed_header_row(matrix)
    if header_row is None:
        return None
    xs, ys = region["xs"], region["ys"]
    native = bool(page.get_text("words"))
    layout = capture_transposed_layout(tokens, region, header_row, native=native)
    output = ParsedActivity(owned_pages={page_no - 1})
    unresolved = {}
    for col in range(1, len(xs) - 1):
        if not declared_compound(matrix[header_row][col]):
            unresolved[col] = "unsupported_header"
            continue
        id_bounds = (xs[col], ys[header_row], xs[col + 1], ys[header_row + 1])
        label, readings, review = read_activity_cell(
            page, tokens, id_bounds, identifier=True, native=native
        )
        if not label:
            unresolved[col] = "no_original_rows"
            continue
        assay = " ".join(
            dict.fromkeys(
                filter(
                    None,
                    (
                        _merged_heading(tokens, region, r, col)
                        for r in range(header_row)
                    ),
                )
            )
        )
        keys = distinct_value_keys(
            [
                _key(f"{assay} {r[0]}", i + 1)
                for i, r in enumerate(matrix[header_row + 1 :])
            ]
        )
        cells = [
            {
                "field": "compound_id",
                "value": label,
                "bbox": list(id_bounds),
                "observations": readings,
            }
        ]
        values = {}
        for row, key in enumerate(keys, header_row + 1):
            metadata = metadata_role(matrix[row][0])
            bounds = (xs[col], ys[row], xs[col + 1], ys[row + 1])
            native_header = native_cell_text(
                tokens, (xs[0], ys[row], xs[1], ys[row + 1])
            )
            review |= header_conflict(native_header, matrix[row][0])
            value, readings, withheld = read_activity_cell(
                page, tokens, bounds, identifier=False, native=native
            )
            if not metadata:
                review |= withheld or "unknown" in key.lower()
            cell = {
                "field": key,
                "value": value,
                "bbox": list(bounds),
                "raw_header": matrix[row][0],
                "raw_native_header": native_header,
                "observations": readings,
                "metric_header_bbox": [xs[0], ys[row], xs[1], ys[row + 1]],
            }
            if metadata:
                cell["physical_column"] = col
                cell = mark_metadata(cell, metadata)
                review |= (
                    cell["metadata_status"] == "unresolved"
                    or withheld
                    and not (not value.strip() and cell["metadata_status"] == "missing")
                )
            else:
                values[key] = value
            cells.append(cell)
        source = {
            "page_no": page_no,
            "table_id": context.table_id,
            "target": context.target,
            "assay": context.assay,
            "cell_line": context.cell_line,
            "raw_caption": context.raw_caption,
            "raw_context": context.raw_context,
            "row": header_row,
            "pair": col,
            "orientation": "transposed",
            "table_bbox": list(region["bbox"]),
            "cells": cells,
            "geometry_space": token_geometry_space(tokens, native),
            "header_region": {
                "page_no": page_no,
                "bbox": [xs[0], ys[0], xs[-1], ys[header_row + 1]],
            },
        }
        output.rows.append(
            ActivityRow(
                cpd=label,
                activity_values=values,
                page_no=page_no,
                table_id=context.table_id,
                source="observed_transposed_cells",
                confidence=0.5 if review else 0.95,
                needs_review=review,
                notes="Original transposed cells; unnamed entities remain unresolved evidence.",
                activity_sources=[source],
            )
        )
        output.headers.extend(values)
    output.coverage.append(
        source_record(
            page_no,
            "grid",
            list(region["bbox"]),
            context.table_id,
            " | ".join(matrix[header_row]),
            "parsed" if output.rows else "unresolved",
            "original_cells" if output.rows else "no_original_rows",
            len(output.rows),
            grid_axes=grid_axes(region),
            transposed_layout=layout,
        )
    )
    output.coverage.extend(
        source_record(
            page_no,
            "grid",
            [xs[col], ys[header_row], xs[col + 1], ys[-1]],
            context.table_id,
            matrix[header_row][col],
            "unresolved",
            reason,
            0,
            column_scope=column_scope(region, col, header_row),
        )
        for col, reason in unresolved.items()
    )
    output.tables.append(
        {
            "table_id": context.table_id,
            "pages": [page_no - 1],
            "heading_page_idx": page_no - 1,
            "heading_text": context.raw_caption,
        }
    )
    return output
