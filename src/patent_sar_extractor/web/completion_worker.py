"""Complete current source chemistry inside the existing owned prediction job."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic

from .admet_history import write_admet_stage
from .completion_inputs import completion_inputs, seed_observations
from .correction_storage import correction_source_fingerprint
from .errors import WebError
from .models import Stage, StageProgress
from .observation_cache import publish_job_cache
from .recognition_storage import RecognitionStore, checked_observation


def complete_structures(
    service,
    analysis,
    row: dict,
    spec,
    core_completed: bool,
    cancel: threading.Event | None,
) -> None:
    from patent_sar_extractor.core.ocsr.smiles_converter import SmilesConverter

    project = service.store.project(spec.project_id)
    rows = {value["id"]: value for value in service.result_rows(spec.project_id)}
    compounds = service.result_queries.effective_compounds(spec.project_id)
    wanted = set(spec.admet_compounds)
    if wanted and not wanted.issubset(rows):
        raise WebError(
            404,
            "compound_not_found",
            "Prediction selection is outside the current table.",
        )
    selected = [value for value in compounds if not wanted or value.id in wanted]
    by_id = {value.id: value for value in selected}
    inputs = completion_inputs(project, rows, selected)
    if not inputs:
        return
    root = Path(spec.output_dir)
    output = root / "recognition"
    output.mkdir(mode=0o700, exist_ok=True)
    cache = output / "raw-observations.sqlite"
    completed = hits = rejected = 0
    started = time.monotonic()

    def publish(status="running", failure=0):
        write_admet_stage(
            root,
            row,
            Stage(
                name="admet",
                status=status,
                count=completed,
                skipped=rejected,
                duration_seconds=time.monotonic() - started,
                progress=StageProgress(
                    completed=completed + failure,
                    total=len(inputs),
                    cache_hits=hits,
                    failures=failure,
                    device=None,
                    peak_rss_mb=None,
                    phase="recognition",
                ),
            ),
            core_completed=core_completed,
        )

    publish()
    storage = RecognitionStore(service.store)
    try:
        # This package-internal lease is the existing sole concurrency authority.
        # Do not change AnalysisService's source/content cache epoch just to add
        # a wrapper: the ADMET algorithm/model inputs have not changed.
        with analysis._operation(cancel):
            seed_observations(project, cache, state=service.store.root)
            converter = SmilesConverter(
                ["decimer"],
                [],
                cache_path=str(cache),
                preprocess=False,
                timeout=180,
                retry_normalization=True,
            )
            try:
                for compound_id, binding, crop in inputs:
                    latest = service.store.job(row["id"])
                    if latest["cancel_requested"] or (
                        cancel is not None and cancel.is_set()
                    ):
                        raise WebError(
                            409,
                            "recognition_cancelled",
                            "Structure completion was cancelled.",
                        )
                    record = converter.convert_one(
                        binding, preprocess_dir=str(output / "inputs")
                    )
                    source = correction_source_fingerprint(project, rows[compound_id])
                    # Persist failed raw producer observations too. A failed
                    # attempt must remain diagnosable without becoming chemistry.
                    write_json_atomic(
                        output / f"{source}.json",
                        {
                            "source_fingerprint": source,
                            "crop_sha256": crop,
                            "job_id": row["id"],
                            "observation": record,
                        },
                    )
                    if record.get("OCSR_status") in {
                        "engine_timeout",
                        "engine_unavailable",
                        "all_engines_failed",
                        "image_missing",
                        "preprocessing_failed",
                    }:
                        raise WebError(
                            502,
                            "recognition_failed",
                            "Structure recognition did not produce a source-bound observation.",
                        )
                    checked = checked_observation(
                        record, compound_id, by_id[compound_id].structure_id
                    )
                    storage.put(
                        spec.project_id,
                        compound_id,
                        source=source,
                        crop=crop,
                        record=record,
                        job_id=row["id"],
                    )
                    completed += 1
                    hits += int(
                        any(
                            attempt.get("from_cache") is True
                            for attempt in record.get("engine_attempts", [])
                        )
                    )
                    rejected += int(checked.status != "valid")
                    publish()
            finally:
                converter.close()
                publish_job_cache(service.store.root, project, cache)
    except Exception:
        publish("failed", int(completed < len(inputs)))
        raise
