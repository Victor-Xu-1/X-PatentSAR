"""Explicit membership catalog; detailed chemistry/statistics stay in region reads."""

from typing import Literal

from ..dto import DTO
from .models import SARJob
from .study_models import StudyRegionSummary
from .study_projection_models import CurrentStudyRegion, CurrentStudyReport
from .study_view_models import ActivityBasis


class CatalogFragment(DTO):
    id: str
    molecule_ids: list[str]
    molecule_count: int
    is_reference: bool
    representation: Literal["port_fragment", "aromatic_graph"] = "port_fragment"


class CatalogRegion(StudyRegionSummary):
    fragments: list[CatalogFragment]


class CatalogReport(CurrentStudyReport):
    regions: list[CatalogRegion]


class StudyCatalog(DTO):
    detail: Literal["catalog"] = "catalog"
    job: SARJob
    report: CatalogReport
    activity_basis: ActivityBasis


class StudyRegionDetail(DTO):
    job: SARJob
    region: CurrentStudyRegion
    activity_basis: ActivityBasis
