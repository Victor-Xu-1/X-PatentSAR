"""Additive read-only preview DTOs; scientific checkpoint identity is unchanged."""

from typing import Literal

from pydantic import Field, model_validator

from ..dto import DTO
from .models import Comparison, Pair, Region, SARJob
from .study_models import StudyRow


class PreviewMoleculeDrawing(DTO):
    id: str = Field(min_length=1, max_length=200)
    svg: str = Field(min_length=1, max_length=1024 * 1024)


class PreviewDrawingPair(DTO):
    reference: PreviewMoleculeDrawing
    candidate: PreviewMoleculeDrawing
    layout: Literal["fixed_background", "independent"]
    equivalent_mappings: int = Field(ge=1, le=64)
    reason: Literal["depiction_failed"] | None = None

    @model_validator(mode="after")
    def layout_status(self):
        if (self.layout == "fixed_background") != (self.reason is None):
            raise ValueError("drawing_layout_status")
        return self


class PreviewMeasurement(DTO):
    context_id: str
    reference_values: list[str]
    candidate_values: list[str]
    comparison: Comparison
    evidence_basis: str
    raw_difference: float | None = None


class PreviewRecordedMeasurement(DTO):
    """Raw source readings, not an inferred direction, delta or SAR conclusion."""

    context_id: str
    reference_values: list[str]
    candidate_values: list[str]


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
    drawings: PreviewDrawingPair | None = None

    @model_validator(mode="after")
    def drawing_identity(self):
        if self.drawings and (
            self.drawings.reference.id != self.reference.molecule_id
            or self.drawings.candidate.id != self.candidate.molecule_id
        ):
            raise ValueError("drawing_pair_identity")
        return self
