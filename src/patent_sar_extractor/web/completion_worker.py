"""Complete original source chemistry inside the existing owned prediction job."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.ocsr.recognition_inputs import ordered_source_results
from patent_sar_extractor.core.ocsr.recognition_policy import (
    UNAVAILABLE_SOURCE_STATUSES,
)

from .admet_history import write_admet_stage
from .completion_inputs import completion_inputs, seed_observations
from .completion_observations import SourceCompletion
from .correction_storage import correction_source_fingerprint
from .errors import WebError
from .models import Stage, StageProgress
from .observation_cache import publish_job_cache
from .recognition_observations import checked_observation
from .recognition_storage import RecognitionStore


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
    attempted = 0
    total_sources = sum(
        1 + len(binding.get("additional_sources", [])) for _, binding, _ in inputs
    )
    started = time.monotonic()
    observations: list[SourceCompletion] = []
    current: SourceCompletion | None = None

    def publish(status="running"):
        failure = max(0, attempted - completed) if status == "failed" else 0
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
                    total=total_sources,
                    cache_hits=hits,
                    failures=failure,
                    device=None,
                    peak_rss_mb=None,
                    phase="recognition",
                ),
            ),
            core_completed=core_completed,
        )

    def check_cancel():
        latest = service.store.job(row["id"])
        if latest["cancel_requested"] or (cancel is not None and cancel.is_set()):
            raise WebError(
                409, "recognition_cancelled", "Structure completion was cancelled."
            )

    def checkpoint(owner: SourceCompletion) -> tuple[dict, str]:
        source = correction_source_fingerprint(project, rows[owner.compound_id])
        record = owner.packet()
        write_json_atomic(
            output / f"{source}.json",
            {
                "source_fingerprint": source,
                "crop_sha256": owner.crop_sha256,
                "job_id": row["id"],
                "observation": record,
            },
        )
        return record, source

    storage = RecognitionStore(service.store)

    def persist(owner: SourceCompletion):
        record, source = checkpoint(owner)
        if any(
            item.get("OCSR_status") in UNAVAILABLE_SOURCE_STATUSES
            for item in owner.records
        ):
            raise WebError(
                502,
                "recognition_failed",
                "Structure recognition did not produce a source-bound observation.",
            )
        if not ordered_source_results(owner.sources, owner.records):
            raise WebError(
                422,
                "recognition_owner",
                "Recognition did not preserve all original source owners.",
            )
        for binding, observed in zip(owner.sources, owner.records, strict=True):
            expected = binding.get("_completion_source_sha256") or owner.crop_sha256
            if observed.get("image_hash") != expected:
                raise WebError(
                    409,
                    "recognition_source_changed",
                    "An approved original image changed during recognition.",
                )
        checked = checked_observation(
            record,
            owner.compound_id,
            by_id[owner.compound_id].structure_id,
            binding=owner.binding,
        )
        storage.put(
            spec.project_id,
            owner.compound_id,
            source=source,
            crop=owner.crop_sha256,
            record=record,
            job_id=row["id"],
        )
        return checked

    publish()
    try:
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
                    current = SourceCompletion(compound_id, binding, crop)
                    for source in current.sources:
                        check_cancel()
                        attempted += 1
                        observed = converter.convert_one(
                            source, preprocess_dir=str(output / "inputs")
                        )
                        current.append(observed)
                        if observed.get("OCSR_status") in UNAVAILABLE_SOURCE_STATUSES:
                            persist(current)
                        completed += 1
                        hits += int(
                            any(
                                attempt.get("from_cache") is True
                                for attempt in observed.get("engine_attempts", [])
                            )
                        )
                        publish()
                    checked = persist(current)
                    current.prior_status = checked.status
                    observations.append(current)
                    rejected += int(checked.status != "valid")
                    publish()
                check_cancel()
                # Raw records stay independent; nested projections never enter
                # the existing bounded post-primary rescue queue.
                converter.finalize_batch(
                    [record for owner in observations for record in owner.records],
                    check_cancel=check_cancel,
                )
                for owner in observations:
                    if any(
                        record.get("stereo_rescue_proof")
                        or record.get("local_stereo_rescue")
                        for record in owner.records
                    ):
                        check_cancel()
                        checked = persist(owner)
                        rejected += int(checked.status != "valid") - int(
                            owner.prior_status != "valid"
                        )
                publish()
            finally:
                converter.close()
                publish_job_cache(service.store.root, project, cache)
    except Exception as exc:
        if current is not None and current.primary is not None:
            try:
                checkpoint(current)  # Retain partial raw evidence, never publish it.
            except (OSError, ValueError, TypeError) as snapshot_error:
                exc.add_note(
                    f"Partial source checkpoint failed: {type(snapshot_error).__name__}"
                )
        publish("failed")
        raise
