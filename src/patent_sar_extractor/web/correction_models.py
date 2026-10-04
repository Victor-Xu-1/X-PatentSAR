"""Bounded, additive API-v1 correction documents; no source-box editing."""

from __future__ import annotations

import math
import unicodedata

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_core import PydanticCustomError

from .correction_chemistry import (
    validate_molfile_text,
    validate_property_basis,
    validate_structure,
)
from .models import DTO, Activity
from .property_values import PropertyOverrides, validate_overrides


def _text(value: object, *, limit: int, required: bool = False) -> None:
    if value is None and not required:
        return
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (required and not value.strip())
        or any(unicodedata.category(char).startswith("C") for char in value)
    ):
        raise ValueError("Correction text is empty, invalid or exceeds its limit")


class EditableFields(DTO):
    display_id: str = Field(min_length=1, max_length=200, strict=True)
    smiles: str | None = Field(max_length=2048, strict=True)
    activities: list[Activity] = Field(max_length=100)
    structure_molfile: str | None = Field(
        default=None, max_length=128 * 1024, strict=True
    )
    property_overrides: PropertyOverrides = Field(default_factory=dict, max_length=6)
    property_basis_smiles: str | None = Field(
        default=None, max_length=2048, strict=True
    )

    @field_validator("display_id", "smiles", "property_basis_smiles")
    @classmethod
    def validate_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        _text(
            value,
            limit=200 if info.field_name == "display_id" else 2048,
            required=info.field_name == "display_id",
        )
        return value

    @field_validator("structure_molfile")
    @classmethod
    def validate_molfile(cls, value: str | None) -> str | None:
        return validate_molfile_text(value)

    @field_validator("property_overrides", mode="before")
    @classmethod
    def validate_properties(cls, value: object) -> object:
        return validate_overrides(value)

    @model_validator(mode="after")
    def validate_addons(self) -> EditableFields:
        validate_structure(self.structure_molfile, self.smiles)
        validate_property_basis(
            self.property_overrides, self.property_basis_smiles, self.smiles
        )
        return self

    @field_validator("activities", mode="before")
    @classmethod
    def validate_measurements(cls, value: object) -> object:
        if not isinstance(value, list) or len(value) > 100:
            raise ValueError("Provide at most 100 activity measurements")
        for item in value:
            data = item.model_dump() if isinstance(item, Activity) else item
            if not isinstance(data, dict):
                raise PydanticCustomError(
                    "activity_object", "Activity measurement must be an object"
                )
            _text(data.get("name"), limit=300, required=True)
            for key, limit in (("unit", 100), ("target", 300), ("assay", 1000)):
                _text(data.get(key), limit=limit)
            scalar = data.get("value")
            if isinstance(scalar, str):
                _text(scalar, limit=1000)
            elif scalar is not None and (
                isinstance(scalar, bool)
                or not isinstance(scalar, (int, float))
                or abs(scalar) > 1e308
                or not math.isfinite(scalar)
            ):
                raise ValueError("Activity value must be a finite scalar")
            page = data.get("page")
            if page is not None and (type(page) is not int or not 1 <= page <= 20000):
                raise ValueError("Activity page must be a bounded original page number")
        return value


class CorrectionRequest(DTO):
    expected_revision: int = Field(ge=0, le=2147483646, strict=True)
    expected_source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
    fields: EditableFields


class CorrectionDocument(DTO):
    source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0)
    basis_fingerprint: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    stale: bool
    has_changes: bool
    original: EditableFields
    values: EditableFields
    updated_at: str | None
