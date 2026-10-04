"""Snake-case Web API v1 DTOs, separate from extraction artifact schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .activity_focus_models import ActivityFocus, ActivitySourceKey
from .activity_rank_models import ActivityStrengthScale, RankValue
from .dto import DTO, Error
from .prediction_models import PredictionSummary
from .property_values import PropertyOverrides, validate_overrides

Decision = Literal["approved", "rejected", "needs_review"]
ConfidenceLevel = Literal["high", "medium", "review", "unknown"]
JobStatus = Literal[
    "queued", "running", "complete", "failed", "cancelled", "interrupted"
]
StageStatus = Literal["pending", "running", "ok", "empty", "failed", "warnings"]
SourceMode = Literal["native", "ocr", "historical", "unavailable"]
STAGES = (
    "classify",
    "activity",
    "locate",
    "structures",
    "bind",
    "smiles",
    "final",
    "qa",
)


class Review(DTO):
    decision: Decision
    note: str
    revision: int
    updated_at: str


class ReviewRequest(DTO):
    decision: Decision
    note: str = Field(default="", max_length=4000)
    expected_revision: int = Field(ge=0)


class Activity(DTO):
    name: str
    value: str | float | int | None
    unit: str | None = None
    target: str | None = None
    assay: str | None = None
    page: int | None = None


class FilterChoice(DTO):
    value: str = Field(max_length=1000)
    count: int = Field(ge=0, le=50_000_000, strict=True)


class ActivityColumn(DTO):
    id: str = Field(
        min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$", strict=True
    )
    name: str
    unit: str | None = None
    target: str | None = None
    assay: str | None = None
    strength_scale: ActivityStrengthScale | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    filter_values: list[FilterChoice] = Field(
        default_factory=list, max_length=200, exclude_if=lambda value: not value
    )
    filter_values_truncated: bool = False


class Source(DTO):
    page: int | None = None
    paragraph: str | None = None
    bbox: list[float] | None = None
    source_label: str | None = None
    correction_reason: str | None = None


class Confidence(DTO):
    level: ConfidenceLevel = "unknown"
    score: float | None = None
    reason: str


class TokenConfidence(DTO):
    minimum: float = Field(ge=0, le=1, strict=True)
    mean: float = Field(ge=0, le=1, strict=True)

    @field_validator("mean")
    @classmethod
    def check_order(cls, value: float, info: ValidationInfo) -> float:
        if value < info.data.get("minimum", 0):
            raise ValueError("Mean token confidence cannot be below the minimum")
        return value


class Recognition(DTO):
    status: Literal["not_run", "valid", "invalid", "unavailable"] = "not_run"
    quality_flag: str | None = None
    model_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    token_confidence: TokenConfidence | None = None


class CorrectionMetadata(DTO):
    revision: int = Field(ge=1, strict=True)
    stale: bool
    has_changes: bool
    updated_at: str


class Compound(DTO):
    id: str
    display_id: str
    structure_id: str | None = None
    structure_image_url: str | None = None
    smiles: str | None = None
    recognition: Recognition = Field(default_factory=Recognition)
    redraw_image_url: str | None = None
    activities: list[Activity]
    activity_source_keys: list[ActivitySourceKey] = Field(
        default_factory=list, max_length=2000, exclude_if=lambda value: not value
    )
    activity_rank_values: list[RankValue | None] = Field(
        default_factory=list, max_length=2000, exclude_if=lambda value: not value
    )
    source: Source
    additional_sources: list[Source] = Field(
        default_factory=list, max_length=1000, exclude_if=lambda value: not value
    )
    confidence: Confidence
    review: Review | None = None
    flags: list[str] = Field(default_factory=list)
    admet: PredictionSummary | None = None
    correction: CorrectionMetadata | None = None
    record_kind: (
        Literal["structure_activity", "structure_only", "activity_only"] | None
    ) = None
    structure_molfile: str | None = Field(
        default=None,
        max_length=128 * 1024,
        strict=True,
        exclude_if=lambda value: not value,
    )
    property_overrides: PropertyOverrides = Field(
        default_factory=dict, max_length=6, exclude_if=lambda value: not value
    )
    # Read-only transport for CSV provenance, deliberately absent from JSON/raw fingerprints.
    property_basis_smiles: str | None = Field(
        default=None, max_length=2048, strict=True, exclude=True
    )

    @field_validator("property_overrides", mode="before")
    @classmethod
    def validate_properties(cls, value: object) -> object:
        return validate_overrides(value)

    @model_validator(mode="after")
    def check_rank_alignment(self) -> Compound:
        if self.activity_rank_values and len(self.activity_rank_values) != len(
            self.activities
        ):
            raise ValueError("Activity ranking values must align with observations")
        return self


class PDFInfo(DTO):
    available: bool
    page_count: int
    sha256: str | None


class Summary(DTO):
    structures: int = 0
    activity_rows: int = 0
    matched_structures: int = 0
    confirmed: int = 0
    needs_review: int = 0
    manually_reviewed: int = 0
    manual_review_pending: int = 0
    structure_only: int = 0
    activity_only: int = 0


class Acceptance(DTO):
    state: Literal["not_run", "accepted", "failed", "historical"]
    errors: list[str] = Field(default_factory=list)


class StageProgress(DTO):
    completed: int = Field(ge=0, le=1_000_000, strict=True)
    total: int = Field(ge=0, le=1_000_000, strict=True)
    cache_hits: int = Field(ge=0, le=1_000_000, strict=True)
    failures: int = Field(ge=0, le=1_000_000, strict=True)
    device: Literal["cpu", "gpu"] | None
    peak_rss_mb: float | None = Field(ge=0, le=1_000_000_000, strict=True)

    @model_validator(mode="after")
    def check_counters(self) -> StageProgress:
        if (
            self.completed > self.total
            or self.cache_hits > self.completed
            or self.failures > self.completed
        ):
            raise ValueError("Stage progress counters are inconsistent")
        return self


class Stage(DTO):
    name: str
    status: StageStatus = "pending"
    count: int | None = Field(default=None, ge=0, le=1_000_000, strict=True)
    duration_seconds: float | None = Field(default=None, ge=0, strict=True)
    reused_checkpoint: bool = Field(default=False, strict=True)
    progress: StageProgress | None = None
    skipped: int = Field(default=0, ge=0, le=1_000_000, strict=True)


class Job(DTO):
    id: str
    project_id: str
    status: JobStatus
    created_at: str
    started_at: str | None
    finished_at: str | None
    error: Error | None
    stages: list[Stage]
    can_resume: bool
    history_available: bool = False
    include_intermediates: bool = False
    force: bool = False
    task_note: str = ""
    include_admet: bool = False
    admet_only: bool = False
    admet_stage: Stage | None = None


class Project(DTO):
    id: str
    title: str
    patent_id: str
    created_at: str
    updated_at: str
    pdf: PDFInfo
    is_historical: bool
    summary: Summary
    acceptance: Acceptance
    last_job: Job | None
    first_structure_page: int | None = Field(default=None, ge=1, strict=True)


class Annotation(DTO):
    compound_id: str
    bbox: list[float]
    kind: str
    verified: bool


class Page(DTO):
    page: int
    page_count: int
    width: float | None
    height: float | None
    image_url: str | None
    text: str
    source_mode: SourceMode
    annotations: list[Annotation]
    activity_focus: ActivityFocus | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class JobRequest(DTO):
    allow_partial: bool = False
    advisory: bool = False
    resume_job_id: str | None = Field(default=None, max_length=64)
    include_intermediates: bool = Field(default=False, strict=True)
    force: bool = Field(default=False, strict=True)
    task_note: str = Field(
        default="",
        max_length=2000,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$",
    )
    include_admet: bool = Field(default=False, strict=True)
    admet_only: bool = Field(default=False, strict=True)


class ExportRequest(DTO):
    format: Literal["csv", "json"]
    compound_ids: list[str] = Field(default_factory=list, max_length=25000)


class Results(DTO):
    items: list[Compound]
    total: int
    page: int
    page_size: int
    metrics: list[str]
    targets: list[str]
    activity_columns: list[ActivityColumn] = Field(
        default_factory=list, max_length=1000
    )
