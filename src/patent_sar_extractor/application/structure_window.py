"""Bounded warm segmentation windows preserve each completed chunk checkpoint."""

from collections.abc import Callable
from pathlib import Path

from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.contracts import (
    SEGMENTATION_INPUT_FINGERPRINT_FILE,
    SEGMENTATION_WINDOW_SCHEMA,
    SEGMENTATION_WINDOW_SCHEMA_VERSION,
    STRUCTURES_SCHEMA,
    STRUCTURES_SCHEMA_VERSION,
    artifact_identity_matches,
    schema_ref,
)

from .pipeline_io import _require_updated_worker_output, _worker_output_state
from .stage_cache import _fingerprint_matches


def execute_missing_windows(
    jobs: list[dict],
    *,
    runner,
    pdf: str,
    root: str,
    script: str,
    patent_id: str,
    crop_regions: str,
    environment: dict,
    cwd: str,
    on_saved: Callable[[list[int]], None] | None = None,
) -> dict[str, dict]:
    results = {}
    for offset in range(0, len(jobs), 3):
        window = jobs[offset : offset + 3]
        for job in window:
            write_json_atomic(
                Path(job["output"]) / SEGMENTATION_INPUT_FINGERPRINT_FILE,
                job["fingerprint"],
            )
        plan_path = Path(root) / ".chunks" / f"window_{offset // 3:03d}.json"
        write_json_atomic(
            plan_path,
            {
                "schema": schema_ref(
                    SEGMENTATION_WINDOW_SCHEMA, SEGMENTATION_WINDOW_SCHEMA_VERSION
                ),
                "jobs": [
                    {
                        "pages": j["pages"],
                        "output": j["output"],
                        "fingerprint_file": str(
                            Path(j["output"]) / SEGMENTATION_INPUT_FINGERPRINT_FILE
                        ),
                    }
                    for j in window
                ],
            },
        )
        previous = {
            j["output"]: _worker_output_state(Path(j["output"]) / "metadata.json")
            for j in window
        }
        args = [
            "--pdf",
            pdf,
            "--output",
            root,
            "--patent-id",
            patent_id,
            "--batch-plan",
            str(plan_path),
        ]
        if crop_regions:
            args += ["--crop-regions", crop_regions]
        proc = runner(
            "decimer",
            script,
            args=args,
            timeout=min(5400, 300 + 120 * sum(len(j["pages"]) for j in window)),
            cwd=cwd,
            env_extra=environment,
            stream_output=True,
        )
        for job in window:
            path = Path(job["output"]) / "metadata.json"
            payload = load_json(path, {})
            if (
                not artifact_identity_matches(
                    payload, STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION
                )
                or payload.get("failed_pages")
                or not isinstance(payload.get("structures"), list)
            ):
                continue
            try:
                _require_updated_worker_output(path, previous[job["output"]])
            except RuntimeError:
                continue
            # A failed later chunk must not throw away earlier successful work.
            if not _fingerprint_matches(str(path), job["fingerprint"]):
                continue
            results[job["output"]] = payload
            if on_saved is not None:
                on_saved(job["pages"])
        if proc.returncode != 0 or any(j["output"] not in results for j in window):
            raise RuntimeError(
                "structure extraction failed in its bounded window; completed chunks retained"
            )
    return results
