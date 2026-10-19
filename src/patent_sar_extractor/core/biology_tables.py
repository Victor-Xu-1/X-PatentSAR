"""Literal biology header semantics for the shared physical-grid reader."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .activity_context_values import context_values
from .activity_continuation_policy import canonical_header
from .activity_header_metrics import METRIC, explicit_unit, normalize_metric_text
from .activity_models import ColumnGroup, GridSchema
from .source_section_roles import section_heading
from .source_table_markers import (
    TABLE_CAPTION_START,
    TABLE_MARKER,
    table_marker_identity,
)


@dataclass(frozen=True)
class BiologySchema:
    table_id: str
    keys: tuple[str, ...]
    kinds: tuple[str, ...]
    pairs: int = 1
    target: str | None = None
    assay: str | None = None
    cell_line: str | None = None
    context_conflicts: bool = False


def infer_schema(context: str, columns: int) -> BiologySchema | None:
    """Require observed biology/header semantics, never specific table numbers."""
    matches = list(TABLE_MARKER.finditer(context))
    if not matches:
        return None
    table_id = table_marker_identity(matches[-1].group())
    recorded, issues = context_values(context)
    if (
        columns == 3
        and re.search(r"\bHTRF\b", context, re.IGNORECASE)
        and re.search(r"\bRatio\b", context, re.IGNORECASE)
    ):
        target = re.search(
            r"([A-Za-z][A-Za-z0-9-]*)\s+binding\s+measured", context, re.IGNORECASE
        )
        prefix = f"{target.group(1)} HTRF" if target else "HTRF"
        return BiologySchema(
            table_id,
            (f"{prefix} ratio", f"{prefix} grade"),
            ("number", "plus"),
            target=target.group(1) if target else None,
            assay="HTRF",
            context_conflicts=bool(issues),
        )
    if columns in {2, 4} and re.search(r"degradation", context, re.IGNORECASE):
        cell_line = recorded["cell_line"]
        protein = re.search(
            r"Ranking\s+of\s+([A-Za-z][A-Za-z0-9-]*)", context, re.IGNORECASE
        )
        if protein is None:
            proteins = list(
                re.finditer(
                    r"([A-Za-z][A-Za-z0-9-]*)\s+degradation", context, re.IGNORECASE
                )
            )
            protein = proteins[-1] if proteins else None
        target = (
            protein.group(1)
            if protein and protein.group(1).lower() != "protein"
            else "Protein"
        )
        prefix = f"{cell_line} " if cell_line else ""
        return BiologySchema(
            table_id,
            (f"{prefix}{target} degradation grade",),
            ("letter",),
            columns // 2,
            target=target if target != "Protein" else None,
            assay="Western blot"
            if re.search(r"Western\s+blot", context, re.IGNORECASE)
            else None,
            cell_line=cell_line,
            context_conflicts=bool(issues),
        )
    if columns == 2 and re.search(r"anti[-\s]?proliferation", context, re.IGNORECASE):
        return BiologySchema(
            table_id,
            ("Anti-proliferation activity grade",),
            ("plus",),
            assay="Anti-proliferation",
            context_conflicts=bool(issues),
        )
    return None


def _context_window(text):
    """Retain same-source pre-caption prose, never an earlier table/section."""
    lines = text.splitlines()
    captions = [
        i for i, line in enumerate(lines) if TABLE_CAPTION_START.match(line.strip())
    ]
    if not captions:
        return text
    current = captions[-1]
    start = current if len(captions) > 1 else 0
    sections = [i for i, line in enumerate(lines[:current]) if section_heading(line)]
    if sections and (len(captions) == 1 or sections[-1] > captions[-2]):
        start = sections[-1]
    return "\n".join(lines[start:])


def biology_grid_schema(schema: GridSchema | None) -> GridSchema | None:
    """Map observed known biology roles, not arbitrary positions or body numbers.

    A generic original header supplies all physical columns. Unknown/metadata or
    actual numeric endpoints cannot escape into a biological interpretation.
    Every repeated pair must have the same printed header, never last-pair wins.
    """
    if schema is None or schema.semantic_kind == "biology":
        return schema
    if (
        schema.needs_review
        or (schema.header_resolution or {}).get("status") == "unresolved"
    ):
        return schema
    header = " ".join(schema.raw_headers)
    normalized = normalize_metric_text(header)
    metrics = list(METRIC.finditer(normalized))
    categorical = metrics and all(
        re.fullmatch(
            r"(?:Ratio|Grade)(?:\s+(?:grade|class))?", m.group().strip(), re.IGNORECASE
        )
        for m in metrics
    )
    if (
        any(g.metadata_columns for g in schema.groups)
        or any(
            any(
                explicit_unit(part)
                for part in re.split(r"[\s()（）]+", schema.raw_headers[column])
                if part
            )
            for group in schema.groups
            for column, _ in group.value_columns
        )
        or re.search(r"\bunknown\b|\?", normalized, re.IGNORECASE)
        or not (
            categorical
            or not metrics
            and re.search(
                r"\b(?:degradation|anti[-\s]?proliferation)\b",
                normalized,
                re.IGNORECASE,
            )
        )
    ):
        return schema
    context = schema.context
    frame = _context_window(context.raw_context)
    bio = infer_schema(f"{frame} {header}", len(schema.raw_headers))
    if (
        bio is None
        or bio.table_id != context.table_id
        or len(schema.groups) != bio.pairs
    ):
        return schema
    groups, kinds, templates = [], [], set()
    for pair, group in enumerate(schema.groups):
        start = pair * (len(bio.keys) + 1)
        expected = tuple(range(start + 1, start + len(bio.keys) + 1))
        if (
            group.id_column != start
            or tuple(c for c, _ in group.value_columns) != expected
        ):
            return schema
        templates.add(tuple(canonical_header(schema.raw_headers[c]) for c in expected))
        groups.append(ColumnGroup(start, tuple(zip(expected, bio.keys))))
        kinds.extend(zip(expected, bio.kinds))
    if len(templates) != 1:
        return schema
    conflict = any(
        old is not None and new is not None and old != new
        for old, new in (
            (context.target, bio.target),
            (context.cell_line, bio.cell_line),
        )
    )
    context = replace(
        context,
        target=context.target or bio.target,
        # A declared assay NAME and an inferred readout METHOD are not the same
        # field. The method already survives in observed biological metric keys;
        # it cannot rename, or alone contradict, an original assay declaration.
        assay=context.assay if context.assay is not None else bio.assay,
        cell_line=context.cell_line or bio.cell_line,
    )
    return replace(
        schema,
        context=context,
        groups=tuple(groups),
        value_kinds=tuple(kinds),
        semantic_kind="biology",
        needs_review=conflict or bio.context_conflicts or bool(context.claim_conflicts),
    )
