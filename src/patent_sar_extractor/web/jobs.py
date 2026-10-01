"""Durable single-consumer extraction queue with bounded ownership recovery."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .attempts import ATTEMPT_VERSION, seed_checkpoints, spec_record
from .checkpoints import LiveCheckpoints
from .errors import WebError
from .files import SafeFiles, private_directory
from .models import Error, Job, JobRequest
from .processes import ProcessIdentity, ProcessRunner, RunSpec, runtime_identity
from .service import WorkspaceService
from .storage import encode, now

logger = logging.getLogger(__name__)


def decode_spec(raw: str) -> RunSpec:
    value = spec_record(raw)
    attempt_version = value.pop("attempt_version", None)
    parent_job = value.pop("resume_job_id", None)
    if (
        attempt_version is not None
        and (type(attempt_version) is not int or attempt_version != ATTEMPT_VERSION)
    ) or (
        parent_job is not None
        and (not isinstance(parent_job, str) or len(parent_job) > 64)
    ):
        raise WebError(
            409, "invalid_job_record", "Persisted job specification is invalid."
        )
    if value.pop("runtime_identity", None) != runtime_identity():
        raise WebError(
            409,
            "resume_identity",
            "Job runtime identity has changed; start a new job instead.",
        )
    try:
        spec = RunSpec(**value)
    except TypeError as exc:
        raise WebError(
            409, "invalid_job_record", "Persisted job specification is invalid."
        ) from exc
    return spec


class JobQueue:
    def __init__(
        self, service: WorkspaceService, runner: ProcessRunner, timeout: float
    ) -> None:
        self.service = service
        self.store = service.store
        self.runner = runner
        self.timeout = timeout
        self.shutdown = threading.Event()
        self.wake = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.reconcile()
        self.thread = threading.Thread(
            target=self._consume, name="patentsar-queue", daemon=True
        )
        self.thread.start()

    def close(self) -> None:
        self.shutdown.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=12)
            if self.thread.is_alive():
                raise WebError(
                    500,
                    "shutdown_incomplete",
                    "Queue did not stop within its shutdown bound.",
                )

    def _spec(self, job_id: str) -> RunSpec:
        row = self.store.job(job_id)
        spec = decode_spec(row["spec"])
        project = self.store.project(row["project_id"])
        output = Path(spec.output_dir)
        expected_pdf = self.store.root / (project["pdf_rel"] or "missing-original")
        if (
            spec.job_id != row["id"]
            or spec.project_id != row["project_id"]
            or self.service.attempts.output(row) != output
            or Path(spec.pdf_path) != expected_pdf
            or spec.sha256 != project["sha256"]
        ):
            raise WebError(
                409,
                "unsafe_job_workspace",
                "Persisted job does not belong to this private workspace; no process was touched.",
            )
        if spec.source_ocr_cache:
            source = Path(spec.source_ocr_cache)
            if any(
                parent.is_symlink() for parent in (source, *source.parents)
            ) or not source.resolve().is_relative_to(
                self.store.root / "runs" / row["project_id"]
            ):
                raise WebError(
                    409,
                    "unsafe_job_workspace",
                    "OCR observations must belong to the same private project.",
                )
        return spec

    def enqueue(self, project_id: str, request: JobRequest) -> Job:
        project = self.store.project(project_id)
        if not project["pdf_rel"]:
            raise WebError(
                409,
                "pdf_required",
                "Attach the verified original PDF before extraction.",
            )
        job_id = uuid.uuid4().hex
        output = self.store.root / "runs" / project_id / job_id
        include_intermediates = request.include_intermediates
        force = request.force
        task_note = request.task_note.strip()
        source_ocr_cache = ""
        old = None
        if project["run_root"] and not request.force and not request.resume_job_id:
            previous_root = Path(project["run_root"])
            candidate = previous_root / "page_classification" / "page_ocr_cache.json"
            project_runs = self.store.root / "runs" / project_id
            if (
                not any(
                    parent.is_symlink()
                    for parent in (previous_root, *previous_root.parents)
                )
                and previous_root.resolve().is_relative_to(project_runs)
                and candidate.is_file()
                and not candidate.is_symlink()
                and candidate.resolve().is_relative_to(project_runs)
            ):
                # Only raw, original-SHA-verified observations are reusable.
                # Current rules regenerate every derived result in a new run.
                from patent_sar_extractor.core.page_ocr_cache import (
                    cache_matches_pdf,
                )

                cache = (
                    SafeFiles(previous_root).json(
                        "page_classification/page_ocr_cache.json"
                    )
                    or {}
                )
                if cache_matches_pdf(cache, str(self.store.root / project["pdf_rel"])):
                    source_ocr_cache = str(candidate)
        if request.resume_job_id:
            previous = self.store.job(request.resume_job_id)
            if (
                previous["project_id"] != project_id
                or not self.service.job(previous["id"]).can_resume
            ):
                raise WebError(
                    409,
                    "resume_unavailable",
                    "This job cannot be safely resumed for this project.",
                )
            old = self._spec(previous["id"])
            if (
                old.advisory != request.advisory
                or old.allow_partial != request.allow_partial
            ):
                raise WebError(
                    409,
                    "resume_parameters",
                    "Resume requires the original job parameters.",
                )
            include_intermediates = old.include_intermediates
            force = (
                False  # Resume reuses verified checkpoints; it never invalidates them.
            )
            task_note = old.task_note
        if any(
            parent.is_symlink() for parent in (output, *output.parents)
        ) or not output.resolve().is_relative_to(self.store.root / "runs"):
            raise WebError(
                400,
                "unsafe_workspace",
                "Job output must remain inside its private workspace.",
            )
        spec = RunSpec(
            job_id,
            project_id,
            str(self.store.root / project["pdf_rel"]),
            str(output),
            project["patent_id"],
            project["sha256"],
            request.allow_partial,
            request.advisory,
            include_intermediates,
            force,
            task_note,
            source_ocr_cache,
        )
        payload = {
            **asdict(spec),
            "runtime_identity": runtime_identity(),
            "attempt_version": ATTEMPT_VERSION,
            "resume_job_id": request.resume_job_id,
        }
        try:
            with self.store.connect(write=True) as connection:
                if (
                    connection.execute(
                        "SELECT COUNT(*) FROM jobs WHERE status='queued'"
                    ).fetchone()[0]
                    >= 100
                ):
                    raise WebError(
                        413, "queue_limit", "Extraction queue has reached its limit."
                    )
                if connection.execute(
                    "SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')",
                    (project_id,),
                ).fetchone():
                    raise WebError(
                        409,
                        "job_active",
                        "Project already has a queued or running extraction.",
                    )
                if output.exists():
                    raise WebError(
                        409,
                        "attempt_exists",
                        "New attempt output directory already exists; no files were changed.",
                    )
                resolved_output = private_directory(output)
                if not resolved_output.is_relative_to(self.store.root / "runs"):
                    raise WebError(
                        400,
                        "unsafe_workspace",
                        "Job output must remain inside its private workspace.",
                    )
                preparation_error = None
                if old is not None:
                    try:
                        seed_checkpoints(old, output)
                    except (WebError, OSError, ValueError, RecursionError) as exc:
                        logger.warning(
                            "Checkpoint preparation failed for attempt %s (%s)",
                            job_id,
                            type(exc).__name__,
                        )
                        preparation_error = Error(
                            code=(
                                exc.code
                                if isinstance(exc, WebError)
                                else "checkpoint_copy_failed"
                            ),
                            message="Checkpoint preparation failed; this attempt and the previous run are preserved.",
                        )
                # Keep the transaction until seeding finishes so the single
                # consumer cannot start against a partially prepared attempt.
                stamp = now()
                connection.execute(
                    "INSERT INTO jobs(id,project_id,status,created_at,finished_at,error,spec) VALUES(?,?,?,?,?,?,?)",
                    (
                        job_id,
                        project_id,
                        "failed" if preparation_error else "queued",
                        stamp,
                        stamp if preparation_error else None,
                        preparation_error.model_dump_json()
                        if preparation_error
                        else None,
                        encode(payload),
                    ),
                )
                connection.execute(
                    "UPDATE projects SET run_root=?,updated_at=? WHERE id=?",
                    (str(output), now(), project_id),
                )
                connection.execute(
                    "DELETE FROM compounds WHERE project_id=?", (project_id,)
                )
                connection.execute(
                    "UPDATE projects SET snapshot=?,historical=0 WHERE id=?",
                    (
                        encode(
                            {
                                "acceptance": {"state": "not_run", "errors": []},
                                "summary": {},
                                "metrics": [],
                                "targets": [],
                                "is_historical": False,
                            }
                        ),
                        project_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise WebError(
                409, "job_active", "Project already has a queued or running extraction."
            ) from exc
        self.wake.set()
        if preparation_error:
            row = self.store.job(job_id)
            self._seal(row, "failed", row["finished_at"])
        return self.service.job(job_id)

    def cancel(self, job_id: str) -> Job:
        with self.store.connect(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise WebError(404, "job_not_found", "Job does not exist.")
            if row["status"] == "queued":
                stamp = now()
                self._seal(dict(row), "cancelled", stamp)
                connection.execute(
                    "UPDATE jobs SET status='cancelled',cancel_requested=1,finished_at=? WHERE id=?",
                    (stamp, job_id),
                )
            elif row["status"] == "running":
                connection.execute(
                    "UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,)
                )
        self.wake.set()
        # Cancellation requests are bounded and asynchronous; the persisted DTO
        # remains running until verified process cleanup actually completes.
        return self.service.job(job_id)

    def _finish(
        self,
        job_id: str,
        status: str,
        error: Error | None,
        *,
        clear_identity: bool = True,
    ) -> None:
        row = self.store.job(job_id)
        if (
            row["status"] in {"complete", "failed", "cancelled", "interrupted"}
            and row["finished_at"]
        ):
            return
        stamp = now()
        self._seal(row, status, stamp)
        with self.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status=?,finished_at=?,error=?,identity=CASE WHEN ? THEN NULL ELSE identity END WHERE id=?",
                (
                    status,
                    stamp,
                    error.model_dump_json() if error else None,
                    clear_identity,
                    job_id,
                ),
            )

    def _seal(self, row: dict[str, Any], status: str, stamp: str) -> None:
        try:
            self.service.attempts.seal(row, status, stamp)
        except (WebError, OSError) as exc:
            # A history failure is explicit unavailable evidence, never a live
            # terminal read from mutable output. Process cleanup still completes.
            logger.warning(
                "Attempt history unavailable for %s (%s)", row["id"], type(exc).__name__
            )

    def reconcile(self) -> None:
        # Caller must hold the per-state WorkspaceOwner before invoking this.
        with self.store.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM jobs WHERE status='running'"
                )
            ]
        for row in rows:
            try:
                spec = self._spec(row["id"])
                if row["identity"]:
                    identity = ProcessIdentity(**json.loads(row["identity"]))
                    cleaned = self.runner.stop(identity, spec)
                    if not cleaned:
                        self._finish(
                            row["id"],
                            "interrupted",
                            Error(
                                code="ownership_unverified",
                                message="Previous process could not be safely reconciled; resume is disabled.",
                            ),
                            clear_identity=False,
                        )
                        continue
                self._finish(
                    row["id"],
                    "interrupted",
                    Error(
                        code="server_interrupted",
                        message="Server stopped during extraction; verified source and checkpoints may be resumed.",
                    ),
                )
            except (WebError, ValueError, TypeError, KeyError) as exc:
                self._finish(
                    row["id"],
                    "interrupted",
                    (
                        Error(code=exc.code, message=exc.message)
                        if isinstance(exc, WebError)
                        else Error(
                            code="invalid_process_record",
                            message="Previous process identity is invalid; no process was touched and resume is disabled.",
                        )
                    ),
                    clear_identity=False,
                )

    def _consume(self) -> None:
        while not self.shutdown.is_set():
            with self.store.connect(write=True) as connection:
                row = connection.execute(
                    "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1"
                ).fetchone()
                if row:
                    connection.execute(
                        "UPDATE jobs SET status='running',started_at=? WHERE id=?",
                        (now(), row["id"]),
                    )
            if row:
                self._execute(row["id"])
            else:
                self.wake.wait(timeout=0.2)
                self.wake.clear()

    def _execute(self, job_id: str) -> None:
        identity = None
        spec = None
        try:
            spec = self._spec(job_id)
            relative = Path(spec.pdf_path).relative_to(self.store.root)
            content = SafeFiles(self.store.root).read(
                relative, max_bytes=128 * 1024 * 1024
            )
            if hashlib.sha256(content).hexdigest() != spec.sha256:
                raise WebError(
                    409,
                    "source_changed",
                    "Original PDF fingerprint changed; extraction was not started.",
                )
            del content
            identity = self.runner.start(spec)
            started = time.monotonic()
            status = "failed"
            error = None
            checkpoints = LiveCheckpoints(
                Path(spec.output_dir), spec.project_id, self.service.refresh
            )
            while True:
                code = self.runner.poll(identity, spec)
                with self.store.connect(write=True) as connection:
                    connection.execute(
                        "UPDATE jobs SET identity=? WHERE id=?",
                        (encode(identity.to_dict()), job_id),
                    )
                    cancel = connection.execute(
                        "SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)
                    ).fetchone()[0]
                if self.shutdown.is_set():
                    status, error = (
                        "interrupted",
                        Error(
                            code="server_interrupted",
                            message="Server stopped; job checkpoints are preserved.",
                        ),
                    )
                    break
                if cancel:
                    status = "cancelled"
                    break
                if time.monotonic() - started >= self.timeout:
                    error = Error(
                        code="job_timeout",
                        message="Extraction exceeded its configured lifetime.",
                    )
                    break
                if code is not None:
                    status = "complete" if code == 0 else "failed"
                    if code != 0:
                        error = Error(
                            code="extraction_failed",
                            message=f"Core CLI exited with status {code}; inspect private run logs.",
                        )
                    break
                checkpoints.update()
                self.shutdown.wait(timeout=0.1)
            cleaned = self.runner.stop(identity, spec)
            if not cleaned:
                status = "interrupted"
                error = Error(
                    code="ownership_unverified",
                    message="Process cleanup could not be verified; resume is disabled.",
                )
            self._finish(job_id, status, error, clear_identity=cleaned)
            self.service.refresh(spec.project_id)
        except Exception as exc:
            logger.exception("Job %s failed at server boundary", job_id)
            cleaned = identity is None
            if identity is not None and spec is not None:
                cleaned = self.runner.stop(identity, spec)
            error = (
                Error(code=exc.code, message=exc.message)
                if isinstance(exc, WebError)
                else Error(
                    code="job_internal",
                    message="Extraction failed at the local process boundary; inspect private run logs.",
                )
            )
            self._finish(job_id, "failed", error, clear_identity=cleaned)
