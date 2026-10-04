"""Review-labelled, deterministic exports with spreadsheet formula escaping."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator, Sequence

from .errors import WebError
from .models import Compound, ExportRequest, Project
from .prediction_models import METRIC_KEYS
from .property_values import effective_property_values, manual_property_values


def formula_safe(value: object) -> str:
    if type(value) in {int, float}:
        # Typed finite numerical observations cannot contain spreadsheet code.
        # Retain negative LogP/LogS as numbers, not apostrophe-prefixed text.
        return str(value)
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
            "Export selection contains records outside the filtered structure/activity table.",
        )
    return [r for r in rows if r.id in ids]


def _manual_change(row: Compound) -> bool:
    return bool(
        manual_property_values(row)
        or row.structure_molfile
        or (row.correction and row.correction.has_changes and not row.correction.stale)
    )


def _research_prediction(row: Compound) -> bool:
    return bool(row.admet and row.admet.status == "complete")


def _unassociated(row: Compound) -> bool:
    return row.record_kind in {"structure_only", "activity_only"}


ADMET_COLUMNS = [
    "admet_status",
    "MW_Dalton",
    "LogP",
    "TPSA_A2",
    "HBD",
    "HBA",
    "LogS_log_mol_L",
    "admet_engine",
    "admet_engine_version",
    "admet_model_sha256",
    "admet_generated_at",
    "admet_source_fingerprint",
    "admet_smiles_sha256",
    "admet_job_id",
    "admet_error_code",
    "admet_error_message",
    "admet_warnings",
    "admet_review_only",
]


def _admet_values(row: Compound) -> list[object]:
    observation = row.admet
    properties = effective_property_values(row)
    if observation is None:
        return [
            "not_run",
            *(properties.get(key) for key in METRIC_KEYS),
            *([None] * 10),
            True,
        ]
    engine = observation.engine
    error = observation.error
    return [
        observation.status,
        *(properties.get(key) for key in METRIC_KEYS),
        engine.name if engine else None,
        engine.version if engine else None,
        engine.model_sha256 if engine else None,
        observation.generated_at,
        observation.source_fingerprint,
        observation.smiles_sha256,
        observation.job_id,
        error.code if error else None,
        error.message if error else None,
        "; ".join(observation.warnings),
        True,
    ]


def export_json(project: Project, rows: list[Compound]) -> Iterator[bytes]:
    header = {
        "project_id": project.id,
        "patent_id": project.patent_id,
        "acceptance": project.acceptance.model_dump(),
        "review_only": project.acceptance.state != "accepted"
        or any(
            _manual_change(row) or _research_prediction(row) or _unassociated(row)
            for row in rows
        ),
        "manual_corrections": sum(_manual_change(row) for row in rows),
        "admet_observations": sum(_research_prediction(row) for row in rows),
        "formal_acceptance_scope": "original_activity_association_only",
        "structure_only": sum(row.record_kind == "structure_only" for row in rows),
        "activity_only": sum(row.record_kind == "activity_only" for row in rows),
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

    def line(values: Sequence[object]) -> bytes:
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
            "display_id",
            "manual_correction",
            "correction_revision",
            "correction_stale",
            "correction_updated_at",
            "record_kind",
        ]
        + ADMET_COLUMNS
        + ["manual_property_keys", "property_basis_smiles"]
    )
    review_only = project.acceptance.state != "accepted" or any(
        _manual_change(row) or _research_prediction(row) or _unassociated(row)
        for row in rows
    )
    for row in rows:
        prefix: list[object] = [
            review_only,
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
        provenance: list[object] = (
            [
                row.display_id,
                _manual_change(row),
                row.correction.revision if row.correction else None,
                row.correction.stale if row.correction else None,
                row.correction.updated_at if row.correction else None,
                row.record_kind,
            ]
            + _admet_values(row)
            + [
                "; ".join(
                    key for key in METRIC_KEYS if key in manual_property_values(row)
                ),
                row.property_basis_smiles if manual_property_values(row) else None,
            ]
        )
        if not row.activities:
            yield line(prefix + [None] * 6 + provenance)
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
                + provenance
            )
