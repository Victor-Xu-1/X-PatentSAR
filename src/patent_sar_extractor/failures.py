"""Single writer and filename authority for fail-closed run markers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    FAILURE_MARKER_SCHEMA,
    FAILURE_MARKER_SCHEMA_VERSION,
    artifact_identity,
)


FAILURE_MARKER_FILENAME = "STRICT_ACCEPTANCE_FAILED.json"


def failure_marker_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / FAILURE_MARKER_FILENAME


def write_failure_marker(output_dir: str | Path, stage: str, errors: Iterable[object]) -> Path:
    normalized_errors = [str(error).strip() for error in errors if str(error).strip()]
    path = failure_marker_path(output_dir)
    write_json_atomic(
        path,
        {
            **artifact_identity(FAILURE_MARKER_SCHEMA, FAILURE_MARKER_SCHEMA_VERSION),
            "stage": str(stage),
            "errors": normalized_errors,
            "failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "deliverables_accepted": False,
        },
    )
    return path


def clear_failure_marker(output_dir: str | Path) -> bool:
    path = failure_marker_path(output_dir)
    if not path.is_file():
        return False
    path.unlink()
    return True
