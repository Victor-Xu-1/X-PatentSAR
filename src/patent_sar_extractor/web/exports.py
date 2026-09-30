"""Review-labelled, deterministic exports with spreadsheet formula escaping."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator

from .errors import WebError
from .models import Compound, ExportRequest, Project


def formula_safe(value: object) -> str:
    text = "" if value is None else str(value)
    # Spreadsheet importers may discard leading whitespace/control characters.
    stripped = text.lstrip(" \t\r\n\v\f\ufeff")
    if stripped.startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def selected(rows: list[Compound], request: ExportRequest) -> list[Compound]:
    if not request.compound_ids:
        return rows
    ids = set(request.compound_ids)
    if any(not x or len(x) > 200 for x in ids):
        raise WebError(
            422, "invalid_selection", "Export selection contains invalid compound IDs."
        )
    known = {r.id for r in rows}
    if not ids.issubset(known):
        raise WebError(
            404,
            "compound_not_found",
            "Export selection contains compounds outside the filtered activity-led results.",
        )
    return [r for r in rows if r.id in ids]


def export_json(project: Project, rows: list[Compound]) -> Iterator[bytes]:
    header = {
        "project_id": project.id,
        "patent_id": project.patent_id,
        "acceptance": project.acceptance.model_dump(),
        "review_only": project.acceptance.state != "accepted",
    }
    yield (
        json.dumps(header, ensure_ascii=False, allow_nan=False)[:-1] + ',"items":['
    ).encode()
    for index, row in enumerate(rows):
        if index:
            yield b","
        yield row.model_dump_json().encode()
    yield b"]}"


def export_csv(project: Project, rows: list[Compound]) -> Iterator[bytes]:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)

    def line(values: list[object]) -> bytes:
        buffer.seek(0)
        buffer.truncate()
        writer.writerow([formula_safe(value) for value in values])
        return buffer.getvalue().encode("utf-8")

    yield b"\xef\xbb\xbf"
    yield line(
        [
            "review_only",
            "acceptance_state",
            "compound_id",
            "structure_id",
            "smiles",
            "source_page",
            "confidence",
            "review_decision",
            "review_note",
            "review_revision",
            "metric",
            "value",
            "unit",
            "target",
            "assay",
            "activity_page",
        ]
    )
    for row in rows:
        prefix: list[object] = [
            project.acceptance.state != "accepted",
            project.acceptance.state,
            row.id,
            row.structure_id,
            row.smiles,
            row.source.page,
            row.confidence.level,
            row.review.decision if row.review else None,
            row.review.note if row.review else None,
            row.review.revision if row.review else None,
        ]
        if not row.activities:
            yield line(prefix + [None] * 6)
        for activity in row.activities:
            yield line(
                prefix
                + [
                    activity.name,
                    activity.value,
                    activity.unit,
                    activity.target,
                    activity.assay,
                    activity.page,
                ]
            )
