"""Additive source identity on read DTOs; never a scientific acceptance flag."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .dto import DTO


class ActivityScopeFields(DTO):
    source_conditions: dict[
        Literal[
            "cell_line",
            "construct",
            "duration",
            "treatment_duration",
            "timepoint",
            "batch",
        ],
        Annotated[str, Field(max_length=1000, strict=True)] | None,
    ] = Field(
        default_factory=dict,
        max_length=6,
        exclude_if=lambda value: not value,
    )
    source_scope: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
        strict=True,
        exclude_if=lambda value: value is None,
    )
    source_table: str | None = Field(
        default=None,
        max_length=300,
        strict=True,
        exclude_if=lambda value: value is None,
    )
    source_context_page: int | None = Field(
        default=None,
        ge=1,
        le=20000,
        strict=True,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def complete_source_identity(self):
        if (
            self.source_table is not None
            and "\x00" in self.source_table
            or any(
                value is not None and "\x00" in value
                for value in self.source_conditions.values()
            )
        ):
            raise ValueError("Invalid original activity context text")
        if (
            self.source_scope is None
            and (
                self.source_table is not None
                or self.source_context_page is not None
                or self.source_conditions
            )
            or self.source_scope is not None
            and self.source_context_page is None
        ):
            raise ValueError("Incomplete original activity context identity")
        return self
