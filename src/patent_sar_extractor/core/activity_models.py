"""Internal activity observations and parsing results; no acceptance policy."""

from __future__ import annotations

from dataclasses import dataclass, field

from .activity_context_values import SCIENTIFIC_CONTEXT_FIELDS, context_values
from .source_role_observations import RoleObservationBuffer
from .source_table_markers import TABLE_BOUNDARY_LINE, unproved_caption_prefix


@dataclass
class ActivityRow:
    """An original row (repeated measurements remain separate observations)."""

    cpd: str = ""
    activity_values: dict = field(default_factory=dict)
    cell_line_data: dict = field(default_factory=dict)
    page_no: int = 0
    table_id: str = ""
    column_side: str = ""
    source: str = "ocr"
    confidence: float = 0.85
    needs_review: bool = False
    notes: str = ""
    activity_sources: list[dict] = field(default_factory=list)


@dataclass
class OCRFixRule:
    """An explicitly configured correction, never an inferred ID/value repair."""

    name: str
    field: str
    pattern: str
    replacement: str
    is_regex: bool = False
    condition: str = ""


@dataclass
class ParsedActivity:
    rows: list[ActivityRow] = field(default_factory=list)
    owned_pages: set[int] = field(default_factory=set)
    tables: list[dict] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    coverage: list[dict] = field(default_factory=list)
    unresolved_rows: list[dict] = field(default_factory=list)
    header_observations: list[dict] = field(default_factory=list)
    role_observations: RoleObservationBuffer = field(
        default_factory=RoleObservationBuffer
    )
    text_pages: dict[str, str] = field(default_factory=dict)
    text_sources: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class TableContext:
    table_id: str = ""
    caption: str = ""
    target: str | None = None
    assay: str | None = None
    cell_line: str | None = None
    raw_caption: str = ""
    body_text: str = ""
    raw_context: str = ""
    construct: str | None = None
    duration: str | None = None
    treatment_duration: str | None = None
    timepoint: str | None = None
    batch: str | None = None

    @property
    def claim_conflicts(self) -> tuple[str, ...]:
        # raw_context retains earlier tables too; raw_caption/body_text are the
        # same existing last-caption scope selected by context_from_text.
        source = "\n".join(part for part in (self.raw_caption, self.body_text) if part)
        source = source if source.strip() else self.raw_context
        conflicts = context_values(source)[1]
        boundary = None
        for boundary in TABLE_BOUNDARY_LINE.finditer(source):
            pass
        if boundary is not None and unproved_caption_prefix(source[boundary.start() :]):
            conflicts += ("table_id:unproved_caption_prefix",)
        return conflicts

    def scientific_values(self) -> dict[str, str | None]:
        # Do not invent optional unknown keys: they would turn a recorded SAR
        # context into a different, artificially incomplete experiment. The
        # existing three source fields retain their legacy nullable shape.
        return {
            key: getattr(self, key)
            for key in SCIENTIFIC_CONTEXT_FIELDS
            if getattr(self, key) is not None or key in ("target", "assay", "cell_line")
        }


@dataclass(frozen=True)
class ColumnGroup:
    id_column: int
    # Each pair is an original physical column and its observed metric label.
    value_columns: tuple[tuple[int, str], ...]
    # Original count columns are owned and retained, never activity endpoints.
    metadata_columns: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True)
class GridSchema:
    context: TableContext
    groups: tuple[ColumnGroup, ...]
    first_data_row: int
    # Optional original physical headers survive adjacent-page continuation.
    # Existing positional constructors and activity schema-v1 dictionaries stay valid.
    raw_headers: tuple[str, ...] = ()
    header_region: tuple[int, tuple[float, float, float, float]] | None = None
    header_resolution: dict | None = None
    source_layout: dict | None = None
    semantic_kind: str = "generic"
    value_kinds: tuple[tuple[int, str], ...] = ()
    needs_review: bool = False
