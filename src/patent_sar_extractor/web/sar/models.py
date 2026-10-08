"""The sole additive API-v1 contract for the independent SAR workbench."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ..dto import DTO

JobState = Literal[
    "queued", "running", "complete", "failed", "cancelled", "interrupted"
]
MatchState = Literal["matched", "not_matched", "ambiguous", "ineligible"]
Comparison = Literal[
    "better", "worse", "equal", "indeterminate", "missing", "context_mismatch"
]


class Metric(DTO):
    id: str
    name: str
    unit: str | None = None
    target: str | None = None
    assay: str | None = None


class Observation(DTO):
    metric_id: str
    value: str
    unit: str | None = None
    context: dict[str, str | None] = Field(default_factory=dict, max_length=8)
    source_page: int | None = None
    source_row: int | None = None
    source_kind: Literal["patent", "imported", "manual"] = "imported"


class Molecule(DTO):
    id: str
    label: str
    smiles: str | None
    molfile: str | None = None
    graph_sha256: str | None = None
    eligible: bool
    issues: list[str] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    source_compound_id: str | None = None
    source_page: int | None = None
    properties: dict[str, float | None] = Field(default_factory=dict, max_length=6)
    predictions: dict[str, float | None] = Field(default_factory=dict, max_length=11)
    property_origins: dict[str, str] = Field(default_factory=dict, max_length=6)
    prediction_origin: str = "not_provided"


class Dataset(DTO):
    id: str
    title: str
    source_kind: Literal["project", "csv"]
    source_project_id: str | None = None
    source_sha256: str
    source_document_sha256: str | None = None
    revision: int = 1
    stale: bool = False
    row_count: int
    input_row_count: int = 0
    eligible_count: int
    issue_count: int
    metrics: list[Metric]
    created_at: str


class DatasetList(DTO):
    items: list[Dataset]
    total: int


class MoleculePage(DTO):
    items: list[Molecule]
    total: int
    page: int
    page_size: int


class CSVPreview(DTO):
    token: str
    filename: str
    headers: list[str]
    row_count: int
    samples: list[dict[str, str]]
    suggested_id: str | None = None
    suggested_smiles: str | None = None
    suggested_activities: list[str]


class CSVMapping(DTO):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    title: str = Field(min_length=1, max_length=200)
    id_column: str = Field(min_length=1, max_length=300)
    smiles_column: str = Field(min_length=1, max_length=300)
    activity_columns: list[str] = Field(min_length=1, max_length=64)
    metric_column: str | None = None
    assay_column: str | None = None
    target_column: str | None = None
    unit_column: str | None = None
    cell_line_column: str | None = None
    duration_column: str | None = None
    source_page_column: str | None = None
    property_columns: dict[str, str] = Field(default_factory=dict, max_length=6)
    prediction_columns: dict[str, str] = Field(default_factory=dict, max_length=11)
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class ProjectSnapshot(DTO):
    project_id: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class Atom(DTO):
    index: int
    element: str
    x: float
    y: float


class MoleculeDrawing(DTO):
    molecule: Molecule
    svg: str
    atoms: list[Atom]


class RegionRequest(DTO):
    molecule_id: str = Field(min_length=1, max_length=200)
    expected_dataset_revision: int = Field(ge=1)
    expected_graph_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    atom_indices: list[Annotated[int, Field(strict=True, ge=0, le=511)]] = Field(
        min_length=1, max_length=512
    )
    name: str = Field(default="Region", min_length=1, max_length=40)
    kind: Literal["variable", "core"] = "variable"


class Region(DTO):
    id: str
    dataset_id: str
    molecule_id: str
    dataset_revision: int
    graph_sha256: str
    atom_indices: list[int]
    attachment_count: int
    created_at: str
    name: str = "Region"
    kind: Literal["variable", "core"] = "variable"


class AnalysisRequest(DTO):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    expected_dataset_revision: int = Field(ge=1)
    region_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    metric_id: str = Field(min_length=1, max_length=200)
    direction: Literal["lower", "higher"]
    grade_order: list[str] = Field(default_factory=list, max_length=32)
    confirm_context: bool = Field(default=False, strict=True)


class SARJob(DTO):
    id: str
    dataset_id: str
    region_id: str
    metric_id: str
    status: JobState
    processed: int = 0
    total: int
    matched: int = 0
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    input_sha256: str
    stale: bool = False
    kind: Literal["reference", "study"] = "reference"


class JobList(DTO):
    items: list[SARJob]
    total: int


class Pair(DTO):
    reference_id: str
    molecule_id: str
    label: str
    match_status: MatchState
    reasons: list[str]
    comparison: Comparison
    reference_values: list[str]
    candidate_values: list[str]
    fold_change: float | None = None
    evidence_basis: Literal["recorded_context", "user_confirmed", "insufficient"]
    region_id: str | None = None
    fragment_id: str | None = None
    variable_atom_indices: list[int] = Field(default_factory=list)
    attachment_mapping: list[list[int]] = Field(default_factory=list)


class PairPage(DTO):
    items: list[Pair]
    total: int
    page: int
    page_size: int
    job: SARJob


class ResumeRequest(DTO):
    expected_input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
