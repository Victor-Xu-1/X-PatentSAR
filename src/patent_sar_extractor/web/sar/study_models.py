"""Typed article-form study contracts; source observations remain immutable.

These are research reports, not extraction acceptance or the author's unpublished
ranking formula. Context IDs select exact recorded experimental conditions.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from ...contracts import SAR_STUDY_REPORT_SCHEMA_VERSION
from ..activity_rank_models import ActivityStrengthScale
from ..dto import DTO
from ..models import Acceptance
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
    strength_method: Literal["tenth_decade", "source", "unclassified"] = "tenth_decade"


class StudyResultPolicy(StudyPolicy):
    # A historical report without this field keeps its captured legacy meaning.
    strength_method: Literal["tenth_decade", "source", "unclassified"] = "source"
    strength_scale: ActivityStrengthScale | None = None


class ConditionDeclaration(DTO):
    context_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    fields: dict[str, str] = Field(min_length=1, max_length=4)
    source_document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_pages: list[Annotated[int, Field(strict=True, ge=1, le=20000)]] = Field(
        min_length=1, max_length=12
    )
    note: str = Field(min_length=1, max_length=2000)


class StudyRequest(DTO):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    expected_dataset_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    policies: list[StudyPolicy] = Field(min_length=1, max_length=8)
    region_ids: list[str] = Field(default_factory=list, max_length=12)
    core_ids: list[str] = Field(default_factory=list, max_length=12)
    confirm_context: bool = Field(default=False, strict=True)
    discover_single_sites: bool = Field(default=False, strict=True)
    candidate_count: int = Field(default=8, ge=5, le=10, strict=True)
    context_declarations: list[ConditionDeclaration] = Field(
        default_factory=list, max_length=8
    )


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
    origin: Literal["manual", "single_site"] = "manual"
    comparison_pool: list[str] | None = None


class StudyDiscovery(DTO):
    method: Literal[
        "single-non-ring-bond-v1",
        "single-region-one-two-cut-v2",
        "single-region-one-two-cut-h-v3",
        "single-region-one-to-three-cut-h-v4",
    ]
    candidate_sites: int = Field(ge=0, le=4096)
    candidate_comparisons: int = Field(ge=0, le=75000)
    indexed_cuts: int = Field(ge=0, le=100000)
    examined_boundaries: int = Field(default=0, ge=0, le=500000)
    indexed_hydrogen_sites: int = Field(default=0, ge=0, le=100000)
    max_cut_bonds: Literal[1, 2, 3] = 1
    excluded: dict[str, int]
    max_variable_atoms: Literal[32] = 32
    max_variable_fraction: Literal[0.4] = 0.4
    min_fixed_atoms: Literal[6] = 6
    limitations: list[str]

    @model_validator(mode="after")
    def exact_method_coverage(self) -> StudyDiscovery:
        expected = {
            "single-non-ring-bond-v1": 1,
            "single-region-one-two-cut-v2": 2,
            "single-region-one-two-cut-h-v3": 2,
            "single-region-one-to-three-cut-h-v4": 3,
        }[self.method]
        if self.max_cut_bonds != expected:
            raise ValueError("discovery_method_coverage")
        if (
            expected > 1
            and not {"max_cut_bonds", "examined_boundaries"} <= self.model_fields_set
        ):
            raise ValueError("discovery_coverage_missing")
        if self.method.endswith(("-h-v3", "-h-v4")) and (
            "indexed_hydrogen_sites" not in self.model_fields_set
            or self.indexed_hydrogen_sites > self.indexed_cuts
        ):
            raise ValueError("discovery_hydrogen_coverage")
        return self


class StudyRow(DTO):
    molecule_id: str
    label: str
    eligible: bool
    scaffold_id: str | None
    values: dict[str, list[str]]
    activity_status: dict[str, str]
    strong: bool
    activity_bands: dict[str, Literal["strong", "medium", "weak", "unclassified"]] = (
        Field(default_factory=dict)
    )
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
    counting_contract: Literal["legacy-per-bin-members", "unique-molecules-v2"] = (
        "legacy-per-bin-members"
    )
    source_acceptance: Acceptance | None = None
    context_declarations: list[ConditionDeclaration] = Field(default_factory=list)
    molecule_count: int
    eligible_count: int
    observation_count: int
    strict_pair_count: int
    matched_pair_count: int = 0
    comparable_pair_count: int = 0
    contexts: list[StudyContext]
    policies: list[StudyResultPolicy]
    distributions: list[StudyDistribution]
    scaffolds: list[StudyScaffold]
    regions: list[StudyRegionSummary]
    candidates: list[StudyRow]
    rows: list[StudyRow]
    warnings: list[str]
    candidate_policy: str = "strict-context-pareto-v1"
    discovery: StudyDiscovery | None = None


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
