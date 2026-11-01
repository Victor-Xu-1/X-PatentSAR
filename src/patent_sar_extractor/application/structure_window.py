"""Bounded warm segmentation windows preserve each completed chunk checkpoint."""

from collections.abc import Callable
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    SEGMENTATION_INPUT_FINGERPRINT_FILE,
    SEGMENTATION_WINDOW_SCHEMA,
    SEGMENTATION_WINDOW_SCHEMA_VERSION,
    schema_ref,
)

from .structure_checkpoint_observer import WindowCheckpointObserver


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
        observer = WindowCheckpointObserver(window, on_saved)
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
            on_line=observer.on_line,
        )
        # Revalidate current files even if live progress already observed them.
        # A later failed chunk never promotes changed or missing earlier data.
        results.update(observer.collect(terminal=True))
        if proc.returncode != 0 or any(j["output"] not in results for j in window):
            raise RuntimeError(
                "structure extraction failed in its bounded window; completed chunks retained"
            )
    return results
