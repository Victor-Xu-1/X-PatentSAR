"""Internal activity observations and parsing results; no acceptance policy."""

from __future__ import annotations

from dataclasses import dataclass, field


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


@dataclass(frozen=True)
class ColumnGroup:
    id_column: int
    # Each pair is an original physical column and its observed metric label.
    value_columns: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class GridSchema:
    context: TableContext
    groups: tuple[ColumnGroup, ...]
    first_data_row: int
    # Optional original physical headers survive adjacent-page continuation.
    # Existing positional constructors and activity schema-v1 dictionaries stay valid.
    raw_headers: tuple[str, ...] = ()
