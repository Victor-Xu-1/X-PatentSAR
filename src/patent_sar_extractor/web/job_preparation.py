"""One durable queued attempt can prepare checkpoints without holding a writer."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .attempts import seed_checkpoints, spec_record
from .dto import Error
from .errors import WebError
from .processes import RunSpec
from .storage import Store, encode, now

logger = logging.getLogger(__name__)


def checkpoint_origin(
    store: Store,
    row: dict[str, Any],
    resolve: Callable[[str], RunSpec],
    unique: Callable[[dict[str, Any]], bool],
) -> RunSpec:
    """A never-started preparation resumes its declared source, not partial copies."""
    seen: set[str] = set()
    for _ in range(16):
        if row["id"] in seen:
            break
        seen.add(row["id"])
        spec = resolve(row["id"])
        if not unique(row):
            raise WebError(
                409,
                "checkpoint_source_unavailable",
                "Declared checkpoint source has ambiguous output ownership.",
            )
        record = spec_record(row["spec"])
        if record.get("checkpoint_preparation", "ready") == "ready":
            return spec
        parent = store.job(record["checkpoint_source_job_id"])
        if (
            parent["project_id"] != row["project_id"]
            or parent["identity"]
            or parent["status"]
            not in {"failed", "cancelled", "interrupted", "complete"}
        ):
            raise WebError(
                409,
                "checkpoint_source_unavailable",
                "Declared checkpoint source is not an inactive owned attempt.",
            )
        row = parent
    raise WebError(
        409,
        "checkpoint_source_invalid",
        "Checkpoint preparation ancestry is invalid; no source was reused.",
    )


def prepare_attempt(
    store: Store, job_id: str, old: RunSpec, output: Path
) -> Error | None:
    def check_cancel() -> None:
        row = store.job(job_id)
        if row["status"] != "queued" or row["cancel_requested"]:
            raise WebError(
                409, "checkpoint_cancelled", "Checkpoint preparation was cancelled."
            )

    error = None
    try:
        seed_checkpoints(old, output, check_cancel=check_cancel)
    except (WebError, OSError, ValueError, RecursionError) as exc:
        logger.warning(
            "Checkpoint preparation failed for %s (%s)", job_id, type(exc).__name__
        )
        error = Error(
            code=exc.code if isinstance(exc, WebError) else "checkpoint_copy_failed",
            message="Checkpoint preparation failed; this attempt and its original source are preserved.",
        )
    with store.connect(write=True) as connection:
        current = connection.execute(
            "SELECT * FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        if current is None or current["status"] != "queued":
            return None  # A committed cancellation remains authoritative.
        record = spec_record(current["spec"])
        if (
            record.get("checkpoint_preparation") != "preparing"
            or record.get("checkpoint_source_job_id") != old.job_id
        ):
            raise WebError(
                409,
                "preparation_state_changed",
                "Attempt preparation identity changed; no task was started.",
            )
        if error is None:
            record["checkpoint_preparation"] = "ready"
        connection.execute(
            "UPDATE jobs SET spec=?,status=?,finished_at=?,error=? WHERE id=? AND status='queued' AND spec=?",
            (
                encode(record),
                "failed" if error else "queued",
                now() if error else None,
                error.model_dump_json() if error else None,
                job_id,
                current["spec"],
            ),
        )
    return error
