"""Additive read-only preview DTOs; scientific checkpoint identity is unchanged."""

from typing import Literal

from pydantic import Field, model_validator

from ..dto import DTO
from .models import Comparison, Pair, Region, SARJob
from .study_models import StudyRow

PropertyComparisonStatus = Literal[
    "comparable", "missing", "origin_unknown", "origin_mismatch", "not_representable"
]


class PreviewMoleculeDrawing(DTO):
    id: str = Field(min_length=1, max_length=200)
    svg: str = Field(min_length=1, max_length=1024 * 1024)


class PreviewDrawingPair(DTO):
    reference: PreviewMoleculeDrawing
    candidate: PreviewMoleculeDrawing
    layout: Literal["fixed_background", "fixed_component", "independent"]
    equivalent_mappings: int = Field(ge=1, le=64)
    reason: Literal["depiction_failed", "layout_clash"] | None = None

    @model_validator(mode="after")
    def layout_status(self):
        if (self.layout != "independent") != (self.reason is None):
            raise ValueError("drawing_layout_status")
        return self


class PreviewMeasurement(DTO):
    context_id: str
    reference_values: list[str]
    candidate_values: list[str]
    comparison: Comparison
    evidence_basis: str
    raw_difference: float | None = None


class RecordedDifference(DTO):
    status: Literal[
        "comparable",
        "missing",
        "context_mismatch",
        "indeterminate",
        "not_scalar",
        "not_representable",
    ]
    value: float | None = None

    @model_validator(mode="after")
    def scalar_status(self):
        if (self.status == "comparable") != (self.value is not None):
            raise ValueError("recorded_difference_status")
        return self


class PreviewRecordedMeasurement(DTO):
    """Raw readings and optional descriptive arithmetic, never a ranking claim."""

    context_id: str
    reference_values: list[str]
    candidate_values: list[str]
    difference: RecordedDifference | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class StudyPreview(DTO):
    job: SARJob
    region: Region
    reference: StudyRow
    candidate: StudyRow
    pair: Pair
    measurements: list[PreviewMeasurement]
    recorded_measurements: list[PreviewRecordedMeasurement] = Field(
        default_factory=list, max_length=1000
    )
    property_differences: dict[str, float | None]
    property_statuses: dict[str, PropertyComparisonStatus] = Field(
        default_factory=dict, max_length=6
    )
    drawings: PreviewDrawingPair | None = None

    @model_validator(mode="after")
    def drawing_identity(self):
        if self.property_statuses and (
            set(self.property_statuses) != set(self.property_differences)
            or any(
                (status == "comparable") != (self.property_differences[key] is not None)
                for key, status in self.property_statuses.items()
            )
        ):
            raise ValueError("property_comparison_status")
        if self.drawings and (
            self.drawings.reference.id != self.reference.molecule_id
            or self.drawings.candidate.id != self.candidate.molecule_id
        ):
            raise ValueError("drawing_pair_identity")
        return self
