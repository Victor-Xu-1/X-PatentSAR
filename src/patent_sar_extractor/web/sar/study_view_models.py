"""Current activity presentation metadata, independent of scientific checkpoints."""

from dataclasses import dataclass
from typing import Literal

from ..dto import DTO
from .study_models import (
    ConditionDeclaration,
    StudyContext,
    StudyOverview,
    StudyRegionSummary,
    StudyResultPolicy,
    StudyRow,
    StudyScaffold,
)
from .study_projection_models import CurrentStudyReport


class ActivityBasis(DTO):
    rule: Literal["numbered-tenth-decades-v1"] = "numbered-tenth-decades-v1"
    anchor_rank: Literal[10] = 10
    source_input_sha256: str
    source_report_sha256: str
    retained_records: int
    excluded_records: dict[str, int]


class CurrentStudyOverview(StudyOverview):
    report: CurrentStudyReport
    activity_basis: ActivityBasis


@dataclass(frozen=True)
class CurrentRecordView:
    """Internal facts view; captured groups supply memberships, never chart counts."""

    molecule_count: int
    molecule_ids: set[str]
    policies: list[StudyResultPolicy]
    contexts: list[StudyContext]
    context_declarations: list[ConditionDeclaration]
    rows: list[StudyRow]
    scaffolds: list[StudyScaffold]
    regions: list[StudyRegionSummary]
    inline_units: bool = False
