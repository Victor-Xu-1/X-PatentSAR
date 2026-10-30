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
    store: Store,
    job_id: str,
    old: RunSpec,
    output: Path,
    *,
    stopping: Callable[[], bool] | None = None,
) -> Error | None:
    def check_cancel() -> None:
        if stopping is not None and stopping():
            raise WebError(
                409,
                "preparation_interrupted",
                "Server stopped while preparing checkpoints; the declared source can be resumed.",
            )
        row = store.job(job_id)
        if row["status"] != "queued" or row["cancel_requested"]:
            raise WebError(
                409, "checkpoint_cancelled", "Checkpoint preparation was cancelled."
            )

    error = None
    try:
        check_cancel()
        seed_checkpoints(old, output, check_cancel=check_cancel)
        check_cancel()
    except (WebError, OSError, ValueError, RecursionError) as exc:
        expected_stop = isinstance(exc, WebError) and exc.code in {
            "checkpoint_cancelled",
            "preparation_interrupted",
        }
        log = logger.info if expected_stop else logger.warning
        log("Checkpoint preparation failed for %s (%s)", job_id, type(exc).__name__)
        error = Error(
            code=exc.code if isinstance(exc, WebError) else "checkpoint_copy_failed",
            message=(
                "Server stopped while preparing checkpoints; the declared source can be resumed."
                if isinstance(exc, WebError) and exc.code == "preparation_interrupted"
                else "Checkpoint preparation failed; this attempt and its original source are preserved."
            ),
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
                (
                    "interrupted"
                    if error and error.code == "preparation_interrupted"
                    else "failed"
                    if error
                    else "queued"
                ),
                now() if error else None,
                error.model_dump_json() if error else None,
                job_id,
                current["spec"],
            ),
        )
    return error


def fail_preparation(store: Store, job_id: str, expected: str, error: Error) -> bool:
    """Fail only the still-queued original preparation; never override cancellation."""
    with store.connect(write=True) as connection:
        return (
            connection.execute(
                "UPDATE jobs SET status='failed',finished_at=?,error=? "
                "WHERE id=? AND status='queued' AND spec=?",
                (now(), error.model_dump_json(), job_id, expected),
            ).rowcount
            == 1
        )


def prepare_oldest_queued(
    store: Store,
    resolve: Callable[[str], RunSpec],
    unique: Callable[[dict[str, Any]], bool],
    stopping: Callable[[], bool],
) -> tuple[str, Error | None] | None:
    """Prepare one oldest owned attempt; leave malformed jobs to the main queue."""
    with store.connect() as connection:
        selected = connection.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1"
        ).fetchone()
    if selected is None:
        return None
    row = dict(selected)
    try:
        record = spec_record(row["spec"])
    except WebError:
        return None
    if record.get("checkpoint_preparation", "ready") != "preparing":
        return None
    try:
        target = resolve(row["id"])
        source = store.job(record["checkpoint_source_job_id"])
        if (
            source["project_id"] != row["project_id"]
            or source["identity"]
            or source["status"]
            not in {"failed", "cancelled", "interrupted", "complete"}
            or spec_record(source["spec"]).get("checkpoint_preparation", "ready")
            != "ready"
            or not unique(source)
        ):
            raise WebError(
                409,
                "checkpoint_source_unavailable",
                "Declared checkpoint source is not an inactive owned attempt.",
            )
        old = resolve(source["id"])
        error = prepare_attempt(
            store, row["id"], old, Path(target.output_dir), stopping=stopping
        )
    except Exception as exc:  # noqa: BLE001 - contain unexpected setup failures in this attempt
        logger.warning(
            "Checkpoint preparation setup failed for %s (%s)",
            row["id"],
            type(exc).__name__,
        )
        error = Error(
            code=exc.code if isinstance(exc, WebError) else "checkpoint_copy_failed",
            message="Checkpoint preparation failed; this attempt and its original source are preserved.",
        )
        if not fail_preparation(store, row["id"], row["spec"], error):
            error = None  # A concurrent cancellation remains authoritative.
    return row["id"], error
