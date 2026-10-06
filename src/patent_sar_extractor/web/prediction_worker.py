"""Owned job phase: one genuine ADMET service, bounded batches, no core-file edits."""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Literal

from .admet_history import read_admet_stage, write_admet_stage
from .analysis import AnalysisService
from .analysis_chemistry import canonical_smiles
from .descriptor_fields import compute_descriptors, descriptor_engine
from .descriptor_models import DescriptorEngine, DescriptorSummary
from .dto import Error
from .errors import WebError
from .models import Stage, StageProgress
from .prediction_fields import selected_metrics
from .prediction_identity import compound_prediction_eligible
from .prediction_models import PredictionEngine, PredictionSummary
from .prediction_storage import PredictionStore, smiles_digest
from .processes import _process
from .service import WorkspaceService
from .storage import now


def wait_for_owner(service: WorkspaceService, job_id: str) -> dict:
    """Do not load a model until the existing carrier persists our kernel identity."""
    deadline = time.monotonic() + 10
    ticks = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19]
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    while time.monotonic() < deadline:
        row = service.store.job(job_id)
        raw = json.loads(row["identity"]) if row["identity"] else {}
        if row["cancel_requested"] or row["status"] != "running":
            raise WebError(409, "admet_cancelled", "ADMET job is no longer active.")
        actual = _process(os.getpid())
        if (
            actual
            and raw.get("pid") == os.getpid()
            and str(raw.get("start_ticks")) == ticks
            and raw.get("boot_id") == boot
            and raw.get("phase") == "admet"
            and all(
                raw.get(key) == actual.get(key)
                for key in ("pid", "start_ticks", "pgid", "argv", "cwd", "executable")
            )
            and service.attempts.output(row) == Path(actual["cwd"])
        ):
            return row
        time.sleep(0.05)
    raise WebError(
        503,
        "admet_owner",
        "ADMET producer ownership was not persisted; no model was loaded.",
    )


def run_predictions(
    service: WorkspaceService,
    analysis: AnalysisService,
    row: dict,
    cancel: threading.Event | None = None,
) -> None:
    from .correction_storage import correction_source_fingerprint
    from .jobs import decode_spec

    spec = decode_spec(row["spec"])
    root = Path(spec.output_dir)
    os.environ["PATENTSAR_PROGRESS_ROOT"] = str(root.resolve())
    os.environ["PATENTSAR_PROGRESS_STAGE"] = "admet"
    _, core_completed = read_admet_stage(row, root)
    from .completion_worker import complete_structures

    complete_structures(service, analysis, row, spec, core_completed, cancel)
    raw_rows = {value["id"]: value for value in service.result_rows(spec.project_id)}
    project = service.store.project(spec.project_id)
    compounds = service.result_queries.effective_compounds(spec.project_id)
    wanted = set(spec.admet_compounds)
    if wanted and not wanted.issubset(raw_rows):
        raise WebError(
            404, "compound_not_found", "ADMET selection is outside the current table."
        )
    compounds = [value for value in compounds if not wanted or value.id in wanted]
    eligible = [value for value in compounds if compound_prediction_eligible(value)]
    skipped = len(compounds) - len(eligible)
    compounds = eligible
    molfiles = {value.id: value.structure_molfile for value in compounds}
    predictions = PredictionStore(service.store)
    inputs = [
        (
            value.id,
            correction_source_fingerprint(project, raw_rows[value.id]),
            value.smiles,
        )
        for value in compounds
    ]
    previous = predictions.summaries(spec.project_id, inputs, molfiles=molfiles)
    total, completed, hits = len(inputs), 0, 0
    attempted = 0
    started = time.monotonic()

    def publish(
        status: Literal["running", "ok", "empty", "failed"], failures: int = 0
    ) -> None:
        write_admet_stage(
            root,
            row,
            Stage(
                name="admet",
                status=status,
                count=completed,
                duration_seconds=time.monotonic() - started,
                skipped=skipped,
                progress=StageProgress(
                    completed=min(total, completed + failures),
                    total=total,
                    cache_hits=hits,
                    failures=failures,
                    device=None,
                    peak_rss_mb=None,
                    phase="properties",
                ),
            ),
            core_completed=core_completed,
        )

    pending = []
    if not inputs:
        publish("empty")
        return
    publish("running")
    try:
        for compound, (compound_id, source, smiles) in zip(compounds, inputs):
            if not smiles:
                attempted = 1
                raise WebError(
                    422,
                    "admet_smiles_required",
                    "An extracted structure is missing validated SMILES.",
                )
            attempted = 1
            canonical = canonical_smiles(smiles)
            # Commit inexpensive calculations independently, before a model is
            # loaded. A later LogS failure cannot erase this completed evidence.
            descriptor = service.descriptors.summaries(
                spec.project_id,
                [(compound_id, source, smiles)],
                molfiles=molfiles,
            )[compound_id]
            if descriptor.status != "complete":
                service.descriptors.put(
                    spec.project_id,
                    compound_id,
                    DescriptorSummary(
                        status="complete",
                        properties=compute_descriptors(canonical),
                        source_fingerprint=source,
                        smiles_sha256=smiles_digest(smiles, compound.structure_molfile),
                        engine=DescriptorEngine.model_validate(descriptor_engine()),
                        generated_at=now(),
                        job_id=row["id"],
                    ),
                )
            current = previous[compound_id]
            if current.status == "complete":
                completed += 1
                hits += 1
            else:
                pending.append((compound_id, source, smiles, canonical))
                predictions.put(
                    spec.project_id,
                    compound_id,
                    PredictionSummary(
                        status="pending",
                        source_fingerprint=source,
                        smiles_sha256=smiles_digest(smiles),
                        job_id=row["id"],
                    ),
                )
        publish("running")
        with analysis.prediction_session(cancel) if pending else nullcontext():
            for offset in range(0, len(pending), 50):
                latest = service.store.job(row["id"])
                if latest["cancel_requested"] or (
                    cancel is not None and cancel.is_set()
                ):
                    raise WebError(409, "admet_cancelled", "ADMET job was cancelled.")
                chunk = pending[offset : offset + 50]
                attempted = len(chunk)
                for compound_id, source, smiles, _ in chunk:
                    predictions.put(
                        spec.project_id,
                        compound_id,
                        PredictionSummary(
                            status="running",
                            source_fingerprint=source,
                            smiles_sha256=smiles_digest(smiles),
                            job_id=row["id"],
                        ),
                    )
                response = analysis.admet([value[3] for value in chunk], cancel=cancel)
                if len(response.predictions) != len(chunk):
                    raise WebError(
                        502, "admet_protocol", "ADMET count differs from its input."
                    )
                for (compound_id, source, smiles, canonical), observation in zip(
                    chunk, response.predictions
                ):
                    if observation.smiles != canonical:
                        raise WebError(
                            502, "admet_protocol", "ADMET belongs to another structure."
                        )
                    predictions.put(
                        spec.project_id,
                        compound_id,
                        PredictionSummary(
                            status="complete",
                            properties=selected_metrics(observation),
                            source_fingerprint=source,
                            smiles_sha256=smiles_digest(smiles),
                            engine=PredictionEngine.model_validate(
                                response.engine.model_dump()
                            ),
                            generated_at=response.generated_at,
                            job_id=row["id"],
                            warnings=response.warnings,
                        ),
                    )
                    completed += 1
                    attempted -= 1
                publish("running")
        publish("ok")
    except Exception as exc:
        error = (
            Error(code=exc.code, message=exc.message)
            if isinstance(exc, WebError)
            else Error(
                code="admet_failed",
                message="ADMET could not produce source-bound predictions.",
            )
        )
        for compound_id, source, smiles, _ in pending:
            existing = predictions.summaries(
                spec.project_id, [(compound_id, source, smiles)], molfiles=molfiles
            )[compound_id]
            if existing.status != "complete":
                predictions.put(
                    spec.project_id,
                    compound_id,
                    PredictionSummary(
                        status="failed",
                        source_fingerprint=source,
                        smiles_sha256=smiles_digest(smiles),
                        job_id=row["id"],
                        error=error,
                    ),
                )
        publish("failed", min(max(1, attempted), total - completed))
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    service = WorkspaceService(args.state_dir)
    row = wait_for_owner(service, args.job_id)
    cancelled = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: cancelled.set())
    signal.signal(signal.SIGINT, lambda *_: cancelled.set())
    analysis = AnalysisService(service.store.root, service)
    try:
        run_predictions(service, analysis, row, cancelled)
    finally:
        analysis.close()


if __name__ == "__main__":
    main()
