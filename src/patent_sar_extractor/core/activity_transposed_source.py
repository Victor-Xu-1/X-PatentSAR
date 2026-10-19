"""Original transposed-table cells and typed unresolved column ownership."""

import re

from .activity_context_geometry import grid_box, valid_box, validate_grid_axes
from .activity_context_values import validate_context_record
from .activity_header_metrics import METRIC, normalize_metric_text
from .activity_identity import LABEL_PREFIX, is_control, normalize_compound
from .activity_metadata import metadata_role
from .activity_transposed_context import capture_transposed_context
from .source_cell_tokens import grid_token_index
from .source_geometry import SourceLayout, SourceTokens, native_region
from .source_observations import source_cell_observation, source_observation_status

MAX_CELLS = 25000


def declared_compound(text):
    # Bare numbers may be concentrations or time points, not original IDs.
    return (
        normalize_compound(text)
        if re.match(LABEL_PREFIX, text, re.IGNORECASE) or is_control(text)
        else ""
    )


def transposed_header_row(matrix):
    if not matrix or len(matrix[0]) < 2:
        return None
    return next(
        (
            i
            for i, row in enumerate(matrix[:3])
            if not row[0].strip()
            and any(declared_compound(value) for value in row[1:])
            and i + 1 < len(matrix)
            and all(
                len(list(METRIC.finditer(normalize_metric_text(part[0])))) == 1
                or metadata_role(part[0])
                for part in matrix[i + 1 :]
            )
            and any(
                METRIC.search(normalize_metric_text(part[0]))
                for part in matrix[i + 1 :]
            )
        ),
        None,
    )


def capture_transposed_layout(page, tokens, region, header_row, context, *, native):
    """Retain each original cell once, including unknown headers and raw values."""
    xs, ys = region["xs"], region["ys"]
    validate_grid_axes({"xs": list(xs), "ys": list(ys)}, grid_box(region))
    if (len(xs) - 1) * (len(ys) - 1) > MAX_CELLS:
        raise ValueError("Original transposed cell inventory exceeds its bound")
    if not isinstance(tokens, SourceTokens):
        raise TypeError("Missing original transposed cell observation")
    selected = grid_token_index(tokens, xs, ys)
    original = grid_token_index(tokens.native_tokens, xs, ys)
    columns = []
    for column in range(len(xs) - 1):
        cells = []
        for row in range(len(ys) - 1):
            bounds = [xs[column], ys[row], xs[column + 1], ys[row + 1]]
            scoped = SourceTokens(
                selected.get((row, column), []),
                SourceLayout(tuple(original.get((row, column), [])), None),
                tokens.scan_bounds,
            )
            observed = source_cell_observation(
                scoped, bounds, native=native_region(scoped, bounds, native)
            )
            cells.append(observed)
        columns.append(cells)
    return {
        "header_row": header_row,
        "columns": columns,
        **capture_transposed_context(page, tokens, region, header_row, context),
    }


def validate_transposed_layout(record):
    layout = record.get("transposed_layout")
    if "transposed_layout" not in record:
        return
    if (
        record["kind"] != "grid"
        or "grid_axes" not in record
        or any(
            key in record
            for key in (
                "layout",
                "parent_grid",
                "column_scope",
                "role_scope",
                "text_scope",
            )
        )
        or record["status"] not in {"parsed", "unresolved"}
        or record["reason"]
        != ("original_cells" if record["status"] == "parsed" else "no_original_rows")
        or not isinstance(layout, dict)
        or set(layout) != {"header_row", "columns", "context", "context_sources"}
        or type(layout["header_row"]) is not int
    ):
        raise ValueError("Malformed original transposed layout")
    axes = record["grid_axes"]
    validate_grid_axes(axes, record["bbox"])
    validate_context_record(layout["context"], record["table_id"])
    if not isinstance(layout["context_sources"], dict):
        raise TypeError("Missing original transposed context observations")
    xs, ys = axes["xs"], axes["ys"]
    columns = layout["columns"]
    if (
        not isinstance(columns, list)
        or len(columns) != len(xs) - 1
        or (len(xs) - 1) * (len(ys) - 1) > MAX_CELLS
        or any(not isinstance(c, list) or len(c) != len(ys) - 1 for c in columns)
    ):
        raise ValueError("Incomplete original transposed cell inventory")
    for column, cells in enumerate(columns):
        for row, cell in enumerate(cells):
            bounds = [xs[column], ys[row], xs[column + 1], ys[row + 1]]
            if (
                not isinstance(cell, dict)
                or source_observation_status(cell, bounds, cell.get("text"))
                == "invalid"
            ):
                raise ValueError("Malformed original transposed cell observation")
    matrix = [[column[row]["text"] for column in columns] for row in range(len(ys) - 1)]
    header = transposed_header_row(matrix)
    if (
        header is None
        or layout["header_row"] != header
        or record["header"] != (" | ".join(matrix[header])[:1024])
    ):
        raise ValueError("Unproved original transposed header roles")


def validate_column_scope(record):
    scope = record.get("column_scope")
    if "column_scope" not in record:
        return
    if (
        record["kind"] != "grid"
        or record["status"] != "unresolved"
        or record["reason"] not in {"unsupported_header", "no_original_rows"}
        or any(
            key in record
            for key in (
                "layout",
                "grid_axes",
                "parent_grid",
                "role_scope",
                "text_scope",
                "transposed_layout",
            )
        )
        or not isinstance(scope, dict)
        or set(scope) != {"parent_grid", "column", "header_row"}
        or not valid_box(scope["parent_grid"])
        or not isinstance(scope["parent_grid"], list)
        or type(scope["column"]) is not int
        or not 1 <= scope["column"] < 500
        or type(scope["header_row"]) is not int
        or not 0 <= scope["header_row"] < 3
    ):
        raise ValueError("Malformed unresolved original column scope")


def column_scope(region, column, header_row):
    return {
        "parent_grid": grid_box(region),
        "column": column,
        "header_row": header_row,
    }
