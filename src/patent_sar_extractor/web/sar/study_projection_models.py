"""Compact validated current-chart objects; captured report contracts stay intact."""

from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass

from ..dto import DTO
from .study_models import (
    StudyDistribution,
    StudyFragment,
    StudyRegionSummary,
    StudyReport,
    StudyScaffold,
)


# Same five scalar wire fields without per-instance dictionary/field sets.
# Each current leaf stays independently mutable; captured StudyBin remains the
# worker/publication/receipt authority. Keep scalar schema metadata identical.
@dataclass(slots=True, kw_only=True, config=DTO.model_config)
class CurrentStudyBin:
    label: str
    kind: str
    observations: int
    molecules: int
    strong: bool = False

    def model_dump(self) -> dict:
        return _bin_adapter.dump_python(self)


_bin_adapter = TypeAdapter(CurrentStudyBin)


class CurrentStudyDistribution(StudyDistribution):
    bins: list[CurrentStudyBin]


class CurrentStudyScaffold(StudyScaffold):
    bins: list[CurrentStudyBin]


class CurrentStudyFragment(StudyFragment):
    bins: list[CurrentStudyBin]


class CurrentStudyRegion(StudyRegionSummary):
    fragments: list[CurrentStudyFragment]


class CurrentStudyReport(StudyReport):
    distributions: list[CurrentStudyDistribution]
    scaffolds: list[CurrentStudyScaffold]
    regions: list[CurrentStudyRegion]
