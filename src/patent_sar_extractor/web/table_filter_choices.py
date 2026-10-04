"""Bounded on-demand distinct values over the existing effective query scan."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from .activity_rank_values import rank_value
from .dto import DTO
from .errors import WebError
from .models import ActivityColumn, Compound, FilterChoice
from .table_queries import column_sort_key
from .table_query_bands import BANDS, Band, row_bands
from .table_query_values import column_values


class BandChoice(DTO):
    value: Band
    count: int = Field(ge=0, le=25000, strict=True)


class ColumnFilterValues(DTO):
    column: str = Field(min_length=1, max_length=100)
    kind: Literal["number", "text", "presence"]
    items: list[FilterChoice] = Field(max_length=200)
    total: int = Field(ge=0, le=25000, strict=True)
    page: int = Field(ge=1, le=25000, strict=True)
    page_size: int = Field(ge=1, le=200, strict=True)
    empty_count: int = Field(ge=0, le=25000, strict=True)
    matching_rows: int = Field(ge=0, le=25000, strict=True)
    bands: list[BandChoice] | None = None


def choice_parameters(column: str, search: str, page: int, page_size: int) -> None:
    if (
        not 1 <= len(column) <= 100
        or len(search) > 500
        or not 1 <= page <= 25000
        or not 1 <= page_size <= 200
    ):
        raise WebError(
            422,
            "filter_choice_limit",
            "Filter value search or pagination exceeds its limit.",
        )
    try:
        search.encode("utf-8")
    except UnicodeError as exc:
        raise WebError(
            422, "invalid_filter_search", "Filter value search must be valid UTF-8."
        ) from exc


def filter_choices(
    rows: Sequence[Compound],
    column: str,
    catalog: Sequence[ActivityColumn],
    *,
    search: str,
    page: int,
    page_size: int,
) -> ColumnFilterValues:
    choices: Counter[str] = Counter()
    counts: Counter[Band] = Counter()
    empty = 0
    numeric_count = text_count = 0
    characters = 0
    scale = next(
        (item.strength_scale for item in catalog if f"activity:{item.id}" == column),
        None,
    )
    for row in rows:
        tokens = {
            str(value).strip()
            for value in column_values(row, column)
            if value is not None and str(value).strip()
        }
        if not tokens:
            empty += 1
        if column.startswith("activity:"):
            # A repeated cell can belong to several colors; each counts once/row.
            counts.update(set(row_bands(row, column, scale)))
        if column == "structure":
            continue  # Never expose authenticated image URLs as checklist values.
        for value in tokens:
            if len(value) > 1000:
                raise WebError(
                    422,
                    "filter_value_limit",
                    "A column value exceeds the checklist limit.",
                )
            parsed = rank_value(value)
            if parsed is not None and parsed[0] == "numeric":
                numeric_count += 1
            else:
                text_count += 1
            if value not in choices:
                characters += len(value)
            choices[value] += 1
            if len(choices) > 25000 or characters > 4_000_000:
                raise WebError(
                    422,
                    "filter_value_limit",
                    "Column choice vocabulary exceeds its safe limit; use a condition filter.",
                )
    kind = (
        "presence"
        if column == "structure"
        else "number"
        if numeric_count > text_count
        or column.startswith("property:")
        or column == "source"
        else "text"
    )
    values = sorted(
        (value for value in choices if search.casefold() in value.casefold()),
        key=lambda value: column_sort_key(value, column),
    )
    offset = (page - 1) * page_size
    return ColumnFilterValues(
        column=column,
        kind=kind,
        items=[
            FilterChoice(value=value, count=choices[value])
            for value in values[offset : offset + page_size]
        ],
        total=len(values),
        page=page,
        page_size=page_size,
        empty_count=empty,
        matching_rows=len(rows),
        bands=[BandChoice(value=band, count=counts[band]) for band in BANDS]
        if column.startswith("activity:")
        else None,
    )
