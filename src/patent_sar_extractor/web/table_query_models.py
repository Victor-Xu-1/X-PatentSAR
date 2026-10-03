"""Bounded workbook queries: data selectors, never executable SQL/formulas."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from .dto import DTO
from .errors import WebError


class ColumnFilter(DTO):
    column: str = Field(min_length=1, max_length=100)
    op: Literal["contains", "eq", "gt", "gte", "lt", "lte", "in", "empty", "not_empty"]
    value: str | None = Field(default=None, max_length=1000)
    values: list[str] | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def check_operand(self) -> ColumnFilter:
        if self.op == "in":
            if self.values is None or any(len(value) > 1000 for value in self.values):
                raise ValueError("Value checklist is missing or excessive")
        elif self.op not in {"empty", "not_empty"} and self.value is None:
            raise ValueError("Filter operand is missing")
        return self


def column_filters(value: str) -> list[ColumnFilter]:
    try:
        if len(value.encode()) > 16 * 1024:
            raise ValueError("Column filters exceed 16 KiB")
        items = json.loads(value or "[]")
        if not isinstance(items, list) or len(items) > 20:
            raise ValueError("At most 20 column filters are supported")
        return [ColumnFilter.model_validate(item) for item in items]
    except (ValueError, ValidationError, UnicodeError, RecursionError) as exc:
        raise WebError(
            422,
            "invalid_column_filter",
            "Column filter specification is invalid or excessive.",
        ) from exc
