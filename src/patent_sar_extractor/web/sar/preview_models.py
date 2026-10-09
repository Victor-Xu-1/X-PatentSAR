"""Additive read-only preview DTOs; scientific checkpoint identity is unchanged."""

from ..dto import DTO
from .models import Comparison, Pair, Region, SARJob
from .study_models import StudyRow


class PreviewMeasurement(DTO):
    context_id: str
    reference_values: list[str]
    candidate_values: list[str]
    comparison: Comparison
    evidence_basis: str
    raw_difference: float | None = None


class StudyPreview(DTO):
    job: SARJob
    region: Region
    reference: StudyRow
    candidate: StudyRow
    pair: Pair
    measurements: list[PreviewMeasurement]
    property_differences: dict[str, float | None]
