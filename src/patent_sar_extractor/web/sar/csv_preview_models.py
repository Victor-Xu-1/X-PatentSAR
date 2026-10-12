"""Additive intake suggestions, isolated from scientific input/report identity."""

from pydantic import Field

from ..dto import DTO
from .models import CSVPreview


class CSVMappingDefaults(DTO):
    columns: dict[str, str] = Field(default_factory=dict, max_length=7)
    property_columns: dict[str, str] = Field(default_factory=dict, max_length=6)
    prediction_columns: dict[str, str] = Field(default_factory=dict, max_length=11)
    ambiguous_roles: list[str] = Field(default_factory=list, max_length=32)


class CSVImportPreview(CSVPreview):
    mapping_defaults: CSVMappingDefaults
