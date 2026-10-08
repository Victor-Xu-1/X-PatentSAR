"""Literal header-role candidates with independently proved original row IDs.

This module has no model/HTTP imports. A selection only identifies an original
physical ID column; existing cell reads, metric parsing and QA still own values.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from .activity_headers import grid_schema, is_id_header
from .activity_identity import is_control, is_value, normalize_compound
from .activity_models import GridSchema, TableContext

HeaderResolver = Callable[[TableContext, list[list[str]], dict, int], GridSchema | None]


def candidate_schemas(
    context: TableContext, matrix: list[list[str]], catalog: frozenset[str]
) -> dict[int, GridSchema]:
    """No anonymous IDs, arbitrary widths, one-row guesses or numeric repair."""
    if (
        not catalog
        or not 3 <= len(matrix) <= 1024
        or not 2 <= len(matrix[0]) <= 32
        or any(len(row) != len(matrix[0]) for row in matrix)
        or any(is_id_header(cell) for row in matrix[:3] for cell in row)
        or any(len(cell) > 4096 for row in matrix for cell in row)
    ):
        return {}
    output = {}
    for column in range(len(matrix[0])):
        if not matrix[0][column].strip():
            continue
        schema = grid_schema(context, matrix, identifier_columns=(column,))
        if schema is None:
            continue
        labels = [
            normalize_compound(row[column]) for row in matrix[schema.first_data_row :]
        ]
        if (
            len(labels) < 2
            or len(set(labels)) != len(labels)
            or any(
                not label or is_control(label) or label not in catalog
                for label in labels
            )
        ):
            continue
        fields = schema.groups[0].value_columns
        if any("unknown" in key.lower() for _, key in fields):
            continue
        if any(
            not is_value(row[index])
            for row in matrix[schema.first_data_row :]
            for index, _ in fields
        ):
            continue
        output[column] = schema
    return output


def header_identity(
    matrix: list[list[str]], schema: GridSchema, page: int, region: dict
) -> str:
    """Source identity includes complete original cells, never an API response."""
    value = {
        "matrix": matrix,
        "header_rows": schema.first_data_row,
        "page": page,
        "xs": region["xs"],
        "ys": region["ys"],
    }
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
