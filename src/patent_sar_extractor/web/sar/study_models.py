"""Typed article-form study contracts; source observations remain immutable.

These are research reports, not extraction acceptance or the author's unpublished
ranking formula. Context IDs select exact recorded experimental conditions.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...contracts import SAR_STUDY_REPORT_SCHEMA_VERSION
from ..dto import DTO
from .models import Region, SARJob


class StudyContext(DTO):
    id: str
    metric_id: str
    name: str
    unit: str | None = None
    context: dict[str, str | None]
    molecule_count: int
    observation_count: int
    distinct_value_count: int
    value_samples: list[str]


class StudyProfile(DTO):
    dataset_id: str
    dataset_revision: int
    contexts: list[StudyContext]
    regions: list[Region]


class StudyPolicy(DTO):
    context_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    direction: Literal["lower", "higher"]
    grade_order: list[str] = Field(default_factory=list, max_length=32)
    strong_threshold: float | None = Field(
        default=None, allow_inf_nan=False, strict=True
    )
    threshold_inclusive: bool = Field(default=True, strict=True)


class StudyRequest(DTO):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    expected_dataset_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    policies: list[StudyPolicy] = Field(min_length=1, max_length=8)
    region_ids: list[str] = Field(default_factory=list, max_length=12)
    core_ids: list[str] = Field(default_factory=list, max_length=12)
    confirm_context: bool = Field(default=False, strict=True)
    candidate_count: int = Field(default=8, ge=5, le=10, strict=True)


class StudyBin(DTO):
    label: str
    kind: str
    observations: int
    molecules: int
    strong: bool = False


class StudyDistribution(DTO):
    context_id: str
    bins: list[StudyBin]
    observed_molecules: int
    observations: int
    missing_molecules: int
    unresolved_molecules: int
    strong_molecules: int


class StudyScaffold(DTO):
    id: str
    smiles: str | None
    molecule_count: int
    strong_count: int
    bins: list[StudyBin]
    molecule_ids: list[str]
    descriptive_only: Literal[True] = True
    assignment_kind: Literal["murcko", "confirmed_core"] = "murcko"
    core_region_id: str | None = None


class StudyFragment(DTO):
    id: str
    smiles: str
    molecule_ids: list[str]
    molecule_count: int
    strong_count: int
    bins: list[StudyBin]
    better: int
    worse: int
    indeterminate: int
    missing: int
    is_reference: bool


class StudyRegionSummary(DTO):
    region: Region
    reference_label: str
    reference_fragment_id: str | None
    fixed_background_sha256: str
    matched: int
    not_matched: int
    ambiguous: int
    ineligible: int
    comparable: int
    no_variation: bool
    fragments: list[StudyFragment]
    independent_backgrounds: Literal[1] = 1


class StudyRow(DTO):
    molecule_id: str
    label: str
    eligible: bool
    scaffold_id: str | None
    values: dict[str, list[str]]
    activity_status: dict[str, str]
    strong: bool
    properties: dict[str, float | None]
    property_origins: dict[str, str]
    predictions: dict[str, float | None] = Field(default_factory=dict)
    prediction_origin: str = "not_provided"
    pareto_front: int | None = None
    candidate_status: Literal[
        "selected", "not_selected", "unranked", "ineligible", "partial"
    ]
    priority_group: int | None = None
    selection_order: int | None = None
    coverage: float
    reasons: list[str]


class StudyReport(DTO):
    schema_version: Literal[1] = SAR_STUDY_REPORT_SCHEMA_VERSION
    dataset_id: str
    dataset_revision: int
    title: str
    input_sha256: str
    engine_sha256: str
    research_only: Literal[True] = True
    article_algorithm_reproduced: Literal[False] = False
    molecule_count: int
    eligible_count: int
    observation_count: int
    strict_pair_count: int
    matched_pair_count: int = 0
    comparable_pair_count: int = 0
    contexts: list[StudyContext]
    policies: list[StudyPolicy]
    distributions: list[StudyDistribution]
    scaffolds: list[StudyScaffold]
    regions: list[StudyRegionSummary]
    candidates: list[StudyRow]
    rows: list[StudyRow]
    warnings: list[str]
    candidate_policy: str = "strict-context-pareto-v1"


class StudyOverview(DTO):
    job: SARJob
    report: StudyReport


class StudyRows(DTO):
    items: list[StudyRow]
    total: int
    page: int
    page_size: int
    job: SARJob


class StudyDrawing(DTO):
    id: str
    svg: str
