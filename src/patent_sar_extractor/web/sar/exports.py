"""Recomputable research-only SAR exports, with one spreadsheet escape authority."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator

from ...contracts import (
    SAR_ENGINE_NAME,
    SAR_ENGINE_VERSION,
    SAR_REPORT_SCHEMA,
    SAR_REPORT_SCHEMA_VERSION,
)
from ..exports import formula_safe
from ..storage import encode
from .queue import SARQueue


def export_json(queue: SARQueue, identifier: str) -> Iterator[bytes]:
    job = queue.view(identifier)
    dataset = queue.service.dataset(job.dataset_id)
    region = queue.service.datasets.region(job.region_id, job.dataset_id)
    spec = json.loads(queue.jobs.record(identifier)["spec"])
    request = spec["request"]
    header = {
        "schema": {"name": SAR_REPORT_SCHEMA, "version": SAR_REPORT_SCHEMA_VERSION},
        "research_only": True,
        "article_reproduction": False,
        "dataset": dataset.model_dump(),
        "region": region.model_dump(),
        "job": job.model_dump(),
        "parameters": request,
        "engine": {
            "name": SAR_ENGINE_NAME,
            "version": SAR_ENGINE_VERSION,
            "sha256": spec["engine_sha256"],
            "producer": spec["producer"],
        },
    }
    yield encode(header)[:-1].encode() + b',"molecules":['
    for index, molecule in enumerate(queue.service.datasets.all(job.dataset_id)):
        yield (b"," if index else b"") + molecule.model_dump_json().encode()
    yield b'],"pairs":['
    used = 0
    for page in range(1, (job.total + 199) // 200 + 1):
        for pair in queue.jobs.pairs(identifier, page, 200).items:
            yield (b"," if used else b"") + pair.model_dump_json().encode()
            used += 1
    yield b"]}\n"


def export_csv(queue: SARQueue, identifier: str) -> Iterator[bytes]:
    job = queue.view(identifier)
    dataset = queue.service.dataset(job.dataset_id)
    region = queue.service.datasets.region(job.region_id, job.dataset_id)
    by_id = {item.id: item for item in queue.service.datasets.all(job.dataset_id)}
    reference = by_id[region.molecule_id]
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)

    def line(values: list) -> bytes:
        buffer.seek(0)
        buffer.truncate()
        writer.writerow([formula_safe(value) for value in values])
        return buffer.getvalue().encode()

    yield b"\xef\xbb\xbf"
    yield line(
        [
            "research_only",
            "source_stale",
            "reference_identifier",
            "identifier",
            "reference_SMILES",
            "SMILES",
            "match_status",
            "comparison",
            "reference_values",
            "candidate_values",
            "fold_change",
            "evidence_basis",
            "reasons",
            "variable_atom_indices_0based",
            "input_sha256",
        ]
    )
    for page in range(1, (job.total + 199) // 200 + 1):
        for pair in queue.jobs.pairs(identifier, page, 200).items:
            yield line(
                [
                    True,
                    dataset.stale,
                    reference.label,
                    pair.label,
                    reference.smiles,
                    by_id[pair.molecule_id].smiles,
                    pair.match_status,
                    pair.comparison,
                    " | ".join(pair.reference_values),
                    " | ".join(pair.candidate_values),
                    pair.fold_change,
                    pair.evidence_basis,
                    "; ".join(pair.reasons),
                    ",".join(map(str, region.atom_indices)),
                    job.input_sha256,
                ]
            )
