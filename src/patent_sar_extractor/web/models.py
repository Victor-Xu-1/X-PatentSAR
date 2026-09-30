"""Snake-case Web API v1 DTOs, separate from extraction artifact schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Error(DTO):
    code: str
    message: str


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


class Compound(DTO):
    id: str
    display_id: str
    structure_id: str | None = None
    structure_image_url: str | None = None
    smiles: str | None = None
    activities: list[Activity]
    source: Source
    confidence: Confidence
    review: Review | None = None
    flags: list[str] = Field(default_factory=list)


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


class Acceptance(DTO):
    state: Literal["not_run", "accepted", "failed", "historical"]
    errors: list[str] = Field(default_factory=list)


class Stage(DTO):
    name: str
    status: StageStatus = "pending"
    count: int | None = None
    duration_seconds: float | None = None


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


class JobRequest(DTO):
    allow_partial: bool = False
    advisory: bool = False
    resume_job_id: str | None = Field(default=None, max_length=64)


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
