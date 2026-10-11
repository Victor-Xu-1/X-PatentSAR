"""Current activity presentation metadata, independent of scientific checkpoints."""

from typing import Literal

from ..dto import DTO
from .study_models import StudyOverview


class ActivityBasis(DTO):
    rule: Literal["numbered-tenth-decades-v1"] = "numbered-tenth-decades-v1"
    anchor_rank: Literal[10] = 10
    source_input_sha256: str
    source_report_sha256: str
    retained_records: int
    excluded_records: dict[str, int]


class CurrentStudyOverview(StudyOverview):
    activity_basis: ActivityBasis
