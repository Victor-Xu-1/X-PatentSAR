"""Pure full-project workbook selection, preserving each original observation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from patent_sar_extractor.core.identifier_order import natural_identifier_key

from .activity_rank_models import ActivityStrengthScale
from .activity_rank_values import rank_value
from .errors import WebError
from .identifier_labels import identifier_equal
from .models import ActivityColumn, Compound
from .prediction_models import METRIC_KEYS
from .table_query_bands import BANDS, row_bands
from .table_query_models import ColumnFilter
from .table_query_values import column_values


def validate_columns(
    filters: Sequence[ColumnFilter],
    sort: str,
    direction: str,
    catalog: Sequence[ActivityColumn],
    sort_band: str = "",
) -> None:
    allowed = (
        {"compound", "structure", "lead", "source", "edit"}
        | {f"activity:{column.id}" for column in catalog}
        | {f"property:{key}" for key in METRIC_KEYS}
    )
    if (
        direction not in {"asc", "desc"}
        or (sort and sort not in allowed)
        or any(item.column not in allowed for item in filters)
        or (sort_band and (sort_band not in BANDS or not sort.startswith("activity:")))
        or any(
            item.op == "band" and not item.column.startswith("activity:")
            for item in filters
        )
    ):
        raise WebError(
            422,
            "invalid_table_column",
            "Sort/filter column or direction is not supported by this project.",
        )
    if any(
        item.op in {"gt", "gte", "lt", "lte"}
        and ((parsed := rank_value(item.value)) is None or parsed[0] != "numeric")
        for item in filters
    ):
        raise WebError(
            422,
            "invalid_numeric_filter",
            "Numeric filter requires one finite exact scalar, not an interval.",
        )


def _equal(actual: Any, expected: str) -> bool:
    left, right = rank_value(actual), rank_value(expected)
    if left is not None and right is not None and left[0] == right[0]:
        return left[1] == right[1]
    return str(actual).strip().casefold() == expected.strip().casefold()


def matches(
    row: Compound,
    criterion: ColumnFilter,
    scale: ActivityStrengthScale | None = None,
) -> bool:
    values = [
        value for value in column_values(row, criterion.column) if str(value).strip()
    ]
    if criterion.op == "empty":
        return not values
    if criterion.op == "not_empty":
        return bool(values)
    if criterion.op == "band":
        return criterion.value in row_bands(row, criterion.column, scale)
    if criterion.op in {"in", "not_in"}:
        if not values:
            return (
                criterion.include_empty
                if criterion.include_empty is not None
                else criterion.op == "not_in"
            )
        chosen = set(criterion.values or [])
        # Checkboxes identify actual distinct raw values, not fuzzy text matches.
        found = (
            any(
                identifier_equal(actual, expected)
                for actual in values
                for expected in chosen
            )
            if criterion.column == "compound"
            else any(str(actual).strip() in chosen for actual in values)
        )
        return found if criterion.op == "in" else not found
    operand = criterion.value or ""
    if criterion.op == "contains":
        return any(operand.casefold() in str(value).casefold() for value in values)
    if criterion.op == "not_contains":
        return all(operand.casefold() not in str(value).casefold() for value in values)
    if criterion.op == "starts_with":
        return any(
            str(value).casefold().startswith(operand.casefold()) for value in values
        )
    if criterion.op == "ends_with":
        return any(
            str(value).casefold().endswith(operand.casefold()) for value in values
        )
    if criterion.op == "eq":
        equal = identifier_equal if criterion.column == "compound" else _equal
        return any(equal(value, operand) for value in values)
    if criterion.op == "ne":
        equal = identifier_equal if criterion.column == "compound" else _equal
        return all(not equal(value, operand) for value in values)
    expected = rank_value(operand)
    if expected is None:
        raise WebError(
            422,
            "invalid_numeric_filter",
            "Numeric filter requires one finite exact scalar, not an interval.",
        )
    for actual in values:
        parsed = rank_value(actual)
        if parsed is None or parsed[0] != expected[0]:
            continue
        a, b = parsed[1], expected[1]
        if (
            (criterion.op == "gt" and a > b)
            or (criterion.op == "gte" and a >= b)
            or (criterion.op == "lt" and a < b)
            or (criterion.op == "lte" and a <= b)
        ):
            return True
    return False


def column_sort_key(value: Any, column: str) -> tuple[Any, ...]:
    parsed = rank_value(value)
    if column == "compound":
        # Printed IDs stay natural (8, 8A, 8B, 10), not lexical 1,10,100,2.
        return (
            0,
            natural_identifier_key(str(value)),
        )
    if parsed is not None:
        return 0, parsed[0], parsed[1]
    return 1, str(value).casefold()


def workbook_rows(
    rows: Sequence[Compound],
    filters: Sequence[ColumnFilter],
    sort: str,
    direction: str,
    catalog: Sequence[ActivityColumn] = (),
    sort_band: str = "",
) -> list[Compound]:
    scales = {f"activity:{column.id}": column.strength_scale for column in catalog}
    output = [
        row
        for row in rows
        if all(matches(row, item, scales.get(item.column)) for item in filters)
    ]
    if not sort:
        return output
    known: list[Compound] = []
    missing: list[Compound] = []
    for row in output:
        values = column_values(row, sort)
        (
            known
            if values and values[0] is not None and str(values[0]).strip()
            else missing
        ).append(row)
    # Multivalued cells use the first observed value, never an average/best value.
    known.sort(
        key=lambda row: column_sort_key(column_values(row, sort)[0], sort),
        reverse=direction == "desc",
    )
    ordered = [*known, *missing]
    if sort_band:
        # Stable partition: chosen color first, retain normal sort within groups.
        # As with scalar ordering, repeated observations use the first, not best.
        ordered.sort(
            key=lambda row: row_bands(row, sort, scales.get(sort))[0] != sort_band
        )
    return ordered
