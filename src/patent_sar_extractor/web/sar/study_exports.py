"""Traceable full-study CSV/JSON/SDF and a passive, printable report."""

from __future__ import annotations

import csv
import hashlib
import io

from ...core.sar.molecules import read_molfile
from ..errors import WebError
from ..exports import formula_safe
from ..prediction_models import METRIC_KEYS
from ..storage import encode
from .study_results import StudyResults


def export_study(queue, identifier: str, format: str):
    if format not in {"json", "csv", "sdf", "html"}:
        raise WebError(422, "sar_export_format", "Choose CSV, JSON, SDF or HTML.")
    job, report = StudyResults(queue).load(identifier)
    record = queue.jobs.record(identifier)
    safe = queue.service.assets.job_files(record["root"], identifier)
    if format == "json":
        original = safe.read("input.json", max_bytes=32 * 1024 * 1024)
        if hashlib.sha256(original).hexdigest() != job.input_sha256:
            raise WebError(409, "sar_input_changed", "Immutable study input differs from its receipt.")

        def content():
            yield encode(
                {
                    "research_only": True,
                    "source_stale": job.stale,
                    "job": job.model_dump(),
                }
            )[:-1].encode()
            yield b',"report":'
            yield safe.read("report.json", max_bytes=32 * 1024 * 1024)
            yield b',"input":'
            yield original
            yield b"}\n"

        return content(), "application/json"
    molecules = queue.service.datasets.all(job.dataset_id)
    by_id = {item.id: item for item in molecules}
    if format == "csv":
        return _csv(job, report, by_id), "text/csv; charset=utf-8"
    if format == "sdf":
        return _sdf(job, report, by_id), "chemical/x-mdl-sdfile"
    # Build and enforce the complete bound before sending download headers.
    return iter([_html(job, report, by_id)]), "text/html; charset=utf-8"


def _csv(job, report, by_id):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)

    def line(values):
        buffer.seek(0)
        buffer.truncate()
        writer.writerow([formula_safe(value) for value in values])
        return buffer.getvalue().encode()

    contexts = [policy.context_id for policy in report.policies]
    names = {item.id: item.name for item in report.contexts}
    yield b"\xef\xbb\xbf"
    yield line(
        [
            "identifier",
            "SMILES",
            "eligible",
            "candidate_status",
            "priority_group",
            "selection_order",
            "strong",
            *[names[key] + " [" + key + "]" for key in contexts],
            *METRIC_KEYS,
            "property_origins",
            "predictions",
            "prediction_origin",
            "source_page",
            "reasons",
            "input_sha256",
            "source_stale",
            "research_only",
        ]
    )
    for row in report.rows:
        molecule = by_id[row.molecule_id]
        yield line(
            [
                row.label,
                molecule.smiles,
                row.eligible,
                row.candidate_status,
                row.priority_group,
                row.selection_order,
                row.strong,
                *[encode(row.values.get(key, [])) for key in contexts],
                *[row.properties.get(key) for key in METRIC_KEYS],
                encode(row.property_origins),
                encode(row.predictions),
                row.prediction_origin,
                molecule.source_page,
                encode(row.reasons),
                job.input_sha256,
                job.stale,
                True,
            ]
        )


def _sdf(job, report, by_id):
    from rdkit import Chem

    for row in report.rows:
        molecule = by_id[row.molecule_id]
        if not molecule.eligible or not molecule.molfile:
            continue  # All excluded records remain in full CSV/JSON, never fabricated.
        mol = read_molfile(molecule.molfile)
        mol.SetProp("_Name", row.label)
        for key, value in {
            "source_identifier": row.label,
            "study_row_json": row.model_dump(),
            "input_sha256": job.input_sha256,
            "research_only": True,
            "source_stale": job.stale,
        }.items():
            # JSON keeps multiline values from injecting another SD record.
            mol.SetProp(key, encode(value))
        output = io.StringIO()
        with Chem.SDWriter(output) as writer:
            writer.write(mol)
        yield output.getvalue().encode()


def _html(job, report, by_id) -> bytes:
    from .study_html import render_report

    return render_report(job, report, by_id)
