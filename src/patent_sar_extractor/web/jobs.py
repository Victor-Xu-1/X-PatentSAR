"""Durable single-consumer extraction queue with bounded ownership recovery."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from patent_sar_extractor.integrations.llm.config import EvidenceResolutionConfig
from patent_sar_extractor.integrations.llm.job_context import (
    create_context,
    read_context,
)

from .admet_history import read_admet_stage, seal_admet_stage, write_admet_stage
from .attempts import ATTEMPT_VERSION, spec_record
from .checkpoints import LiveCheckpoints
from .core_research_policy import completed_qa_rejection
from .errors import WebError
from .files import SafeFiles, private_directory
from .history_storage import ensure_job_visible, ensure_project_visible
from .job_phases import OwnedPhase, PhaseResult
from .job_preparation import checkpoint_origin, prepare_attempt
from .job_recovery import decode_identity, preserve_cleanup, release_retained_identity
from .models import Error, Job, JobRequest, Stage
from .prediction_jobs import correction_prediction, enqueue_prediction
from .processes import (
    ProcessIdentity,
    ProcessRunner,
    RunSpec,
    runtime_identity,
    runtime_identity_matches,
)
from .service import WorkspaceService
from .storage import encode, now

logger = logging.getLogger(__name__)


def decode_spec(raw: str) -> RunSpec:
    value = spec_record(raw)
    attempt_version = value.pop("attempt_version", None)
    parent_job = value.pop("resume_job_id", None)
    value.pop("checkpoint_preparation", None)
    value.pop("checkpoint_source_job_id", None)
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
    if not runtime_identity_matches(value.pop("runtime_identity", None)):
        raise WebError(
            409,
            "resume_identity",
            "Job runtime identity has changed; start a new job instead.",
        )
    try:
        value["admet_compounds"] = tuple(value.get("admet_compounds", ()))
        spec = RunSpec(**value)
        if spec.llm_context_id and not re.fullmatch(
            r"[a-f0-9]{32}", spec.llm_context_id
        ):
            raise TypeError("Invalid API context identity")
    except TypeError as exc:
        raise WebError(
            409, "invalid_job_record", "Persisted job specification is invalid."
        ) from exc
    return spec


class JobQueue:
    def __init__(
        self,
        service: WorkspaceService,
        runner: ProcessRunner,
        timeout: float,
        *,
        llm_policy: Callable[[], EvidenceResolutionConfig] | None = None,
    ) -> None:
        self.service = service
        self.store = service.store
        self.runner = runner
        self.timeout = timeout
        self.llm_policy = llm_policy or EvidenceResolutionConfig
        self.shutdown = threading.Event()
        self.wake = threading.Event()
        self.thread: threading.Thread | None = None
        self.phases = OwnedPhase(self.store, self.runner, self.shutdown)

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
        expected_pdf = self.store.locations.pdf_path(project)
        if (
            spec.job_id != row["id"]
            or spec.project_id != row["project_id"]
            or self.service.attempts.output(row) != output
            or Path(spec.pdf_path) != expected_pdf
            or spec.sha256 != project["sha256"]
            or spec.workspace_root not in {"", str(self.store.root)}
            or (
                not spec.workspace_root
                and not output.is_relative_to(self.store.root / "runs")
            )
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
                self.store.locations.result_anchor(source) / row["project_id"]
            ):
                raise WebError(
                    409,
                    "unsafe_job_workspace",
                    "OCR observations must belong to the same private project.",
                )
        return spec

    def enqueue(self, project_id: str, request: JobRequest) -> Job:
        self.store.project(project_id)
        if request.resume_job_id:
            self.service.job(request.resume_job_id)
        if request.admet_only:
            self.service._current_project(project_id)
            if (
                request.resume_job_id
                or request.force
                or request.advisory
                or request.allow_partial
                or not request.include_admet
            ):
                raise WebError(
                    422,
                    "admet_parameters",
                    "Prediction-only jobs cannot change extraction parameters.",
                )
            with self.store.connect(write=True) as connection:
                job_id = enqueue_prediction(self.store, connection, project_id)
            self.wake.set()
            return self.service.job(job_id)
        if request.resume_job_id:
            old_prediction = self._spec(request.resume_job_id)
            if old_prediction.admet_only:
                if (
                    old_prediction.project_id != project_id
                    or not self.service.job(request.resume_job_id).can_resume
                ):
                    raise WebError(
                        409,
                        "resume_unavailable",
                        "This prediction job cannot be resumed.",
                    )
                with self.store.connect(write=True) as connection:
                    ensure_job_visible(connection, request.resume_job_id)
                    job_id = enqueue_prediction(
                        self.store,
                        connection,
                        project_id,
                        compound_ids=old_prediction.admet_compounds,
                    )
                self.wake.set()
                return self.service.job(job_id)
        project = self.store.project(project_id)
        if not project["pdf_rel"]:
            raise WebError(
                409,
                "pdf_required",
                "Attach the verified original PDF before extraction.",
            )
        job_id = uuid.uuid4().hex
        result_root = self.store.locations.result_root()
        output = result_root / project_id / job_id
        include_intermediates = request.include_intermediates
        include_admet = request.include_admet
        force = request.force
        task_note = request.task_note.strip()
        source_ocr_cache = ""
        old = None
        if project["run_root"] and not request.force and not request.resume_job_id:
            previous_root = Path(project["run_root"])
            candidate = previous_root / "page_classification" / "page_ocr_cache.json"
            try:
                project_runs = (
                    self.store.locations.result_anchor(previous_root) / project_id
                )
            except WebError as error:
                if error.code != "storage_output":
                    raise
                project_runs = (
                    None  # Read-only imported runs are not owned checkpoints.
                )
            if (
                project_runs is not None
                and not any(
                    parent.is_symlink()
                    for parent in (previous_root, *previous_root.parents)
                )
                and previous_root.resolve().is_relative_to(project_runs)
                and candidate.is_file()
                and not candidate.is_symlink()
                and candidate.resolve().is_relative_to(project_runs)
            ):
                # Compatible old observations survive independently of rules.
                # Derived reuse below requires exact current identity as well.
                from patent_sar_extractor.core.page_ocr_cache import (
                    cache_matches_pdf,
                )

                cache = (
                    SafeFiles(previous_root).json(
                        "page_classification/page_ocr_cache.json"
                    )
                    or {}
                )
                if cache_matches_pdf(
                    cache, str(self.store.locations.pdf_path(project))
                ):
                    source_ocr_cache = str(candidate)
                    with self.store.connect() as connection:
                        row = connection.execute(
                            "SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                            (project_id,),
                        ).fetchone()
                    previous = dict(row) if row else None
                    if (
                        previous
                        and previous["status"]
                        in {"complete", "failed", "cancelled", "interrupted"}
                        and not previous["identity"]
                        and self.service.attempts.output(previous) == previous_root
                    ):
                        # Raw OCR compatibility is independent of the ruleset
                        # that first observed it. cache_matches_pdf already
                        # verifies that contract; the existing transport/CLI
                        # gates validate every derived checkpoint separately.
                        try:
                            old = self._spec(previous["id"])
                        except WebError as exc:
                            if exc.code != "resume_identity":
                                raise
                            logger.info(
                                "Derived checkpoint reuse skipped for changed runtime identity"
                            )
                        else:
                            # The same bounded transport as explicit resume.
                            # This copies observations/checkpoints, not history,
                            # acceptance or old task parameters. CLI gates remain.
                            source_ocr_cache = ""
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
            saved_options = self._spec(previous["id"])
            old = checkpoint_origin(
                self.store, previous, self._spec, self.service.attempts.unique
            )
            if (
                saved_options.advisory != request.advisory
                or saved_options.allow_partial != request.allow_partial
            ):
                raise WebError(
                    409,
                    "resume_parameters",
                    "Resume requires the original job parameters.",
                )
            include_intermediates = saved_options.include_intermediates
            force = (
                False  # Resume reuses verified checkpoints; it never invalidates them.
            )
            task_note = saved_options.task_note
            include_admet = saved_options.include_admet
        if any(
            parent.is_symlink() for parent in (output, *output.parents)
        ) or not output.resolve().is_relative_to(result_root):
            raise WebError(
                400,
                "unsafe_workspace",
                "Job output must remain inside its private workspace.",
            )
        spec = RunSpec(
            job_id,
            project_id,
            str(self.store.locations.pdf_path(project)),
            str(output),
            project["patent_id"],
            project["sha256"],
            request.allow_partial,
            request.advisory,
            include_intermediates,
            force,
            task_note,
            source_ocr_cache,
            include_admet,
            workspace_root=str(self.store.root),
            llm_context_id=job_id,
        )
        new_api_policy = None
        try:
            if request.resume_job_id and saved_options.llm_context_id:
                identifier = saved_options.llm_context_id
                context = read_context(
                    self.store.root / "llm" / f"{identifier}.policy.json"
                )
                if context.original_sha256 != spec.sha256:
                    raise ValueError("API snapshot original differs")
                spec = replace(spec, llm_context_id=identifier)
            else:
                policy = (
                    EvidenceResolutionConfig()
                    if request.resume_job_id
                    else self.llm_policy()
                )
                policy.validate()
                new_api_policy = policy
        except (OSError, ValueError, TypeError) as error:
            raise WebError(
                409,
                "llm_configuration",
                "API settings or the saved task policy are invalid; no model call was made.",
            ) from error
        payload = {
            **asdict(spec),
            "runtime_identity": runtime_identity(),
            "attempt_version": ATTEMPT_VERSION,
            "resume_job_id": request.resume_job_id,
            "checkpoint_preparation": "preparing" if old is not None else "ready",
            "checkpoint_source_job_id": old.job_id if old is not None else None,
        }
        try:
            with self.store.connect(write=True) as connection:
                ensure_project_visible(connection, project_id)
                if request.resume_job_id:
                    ensure_job_visible(connection, request.resume_job_id)
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
                if not resolved_output.is_relative_to(result_root):
                    raise WebError(
                        400,
                        "unsafe_workspace",
                        "Job output must remain inside its private workspace.",
                    )
                if new_api_policy is not None:
                    try:
                        create_context(
                            self.store.root, job_id, spec.sha256, new_api_policy
                        )
                    except (OSError, ValueError, TypeError) as error:
                        raise WebError(
                            409,
                            "llm_configuration",
                            "API context could not be reserved; no model call was made.",
                        ) from error
                # Reserve a durable queued attempt. Its readiness stays false
                # until bounded checkpoint preparation finishes outside SQLite.
                stamp = now()
                connection.execute(
                    "INSERT INTO jobs(id,project_id,status,created_at,finished_at,error,spec) VALUES(?,?,?,?,?,?,?)",
                    (
                        job_id,
                        project_id,
                        "queued",
                        stamp,
                        None,
                        None,
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
        preparation_error = (
            prepare_attempt(self.store, job_id, old, output)
            if old is not None
            else None
        )
        self.wake.set()
        if preparation_error:
            row = self.store.job(job_id)
            self._seal(row, "failed", row["finished_at"])
        return self.service.job(job_id)

    def cancel(self, job_id: str) -> Job:
        with self.store.connect(write=True) as connection:
            ensure_job_visible(connection, job_id)
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
                self.service.predictions.finish_job(
                    connection, job_id, "cancelled", None
                )
                self.service.descriptors.finish_job(
                    connection, job_id, "cancelled", None
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
        self._seal(row, status, stamp, error)
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
            self.service.predictions.finish_job(connection, job_id, status, error)
            self.service.descriptors.finish_job(connection, job_id, status, error)

    def _seal(
        self, row: dict[str, Any], status: str, stamp: str, error: Error | None = None
    ) -> None:
        # Core facts must be sealed independently: an unavailable research
        # envelope must never skip or overwrite the immutable eight-stage log.
        try:
            self.service.attempts.seal(row, status, stamp)
        except (WebError, OSError, ValueError) as exc:
            # A history failure is explicit unavailable evidence, never a live
            # terminal read from mutable output. Process cleanup still completes.
            logger.warning(
                "Attempt history unavailable for %s (%s)", row["id"], type(exc).__name__
            )
        try:
            root = self.service.attempts.output(row)
            if root is not None and spec_record(row["spec"]).get("include_admet"):
                research_complete = bool(
                    error
                    and error.code == "core_not_accepted"
                    and status == "failed"
                    and completed_qa_rejection(root)
                )
                seal_admet_stage(
                    self.store.root,
                    root,
                    row,
                    status,
                    stamp,
                    research_complete=research_complete,
                )
        except (WebError, OSError, ValueError) as exc:
            logger.warning(
                "ADMET history unavailable for %s (%s)", row["id"], type(exc).__name__
            )

    def reconcile(self) -> None:
        # Caller must hold the per-state WorkspaceOwner before invoking this.
        with self.store.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM jobs WHERE status IN ('running','queued') OR (status='interrupted' AND identity IS NOT NULL)"
                )
            ]
        for row in rows:
            try:
                if any(
                    not isinstance(row.get(key), str)
                    or not re.fullmatch(r"[a-f0-9]{32}", row[key])
                    for key in ("id", "project_id")
                ):
                    raise WebError(
                        409,
                        "invalid_job_record",
                        "Recovery needs canonical owned workspace identities; no process was touched.",
                    )
                spec = self._spec(row["id"])
                if (
                    spec_record(row["spec"]).get("checkpoint_preparation", "ready")
                    == "preparing"
                ):
                    if row["identity"]:
                        raise WebError(
                            409,
                            "invalid_process_record",
                            "An unprepared attempt must not have a producer identity.",
                        )
                    self._finish(
                        row["id"],
                        "interrupted",
                        Error(
                            code="preparation_interrupted",
                            message="Server stopped while preparing checkpoints; the declared source can be resumed.",
                        ),
                    )
                    continue
                if row["status"] == "queued":
                    continue
                if row["identity"]:
                    identity = decode_identity(row["identity"])
                    cleaned = self.runner.stop(
                        identity, self._phase_spec(spec, identity)
                    )
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
                    preserve_cleanup(self.store, row, identity, self.runner)
                    if row["status"] == "interrupted":
                        release_retained_identity(self.store, row)
                        continue
                self._finish(
                    row["id"],
                    "interrupted",
                    Error(
                        code="server_interrupted",
                        message="Server stopped during extraction; verified source and checkpoints may be resumed.",
                    ),
                )
            except (WebError, OSError, ValueError, TypeError, KeyError) as exc:
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

    def _claim_ready(self) -> dict[str, Any] | None:
        # Idle polling is read-only. Slow preparation cannot starve API writers
        # or start the CLI on a partially copied directory.
        with self.store.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 100"
                )
            ]
        for row in rows:
            try:
                if (
                    spec_record(row["spec"]).get("checkpoint_preparation", "ready")
                    != "ready"
                ):
                    continue
            except WebError:
                pass  # _execute rejects the record before launching anything.
            with self.store.connect(write=True) as connection:
                changed = connection.execute(
                    "UPDATE jobs SET status='running',started_at=? WHERE id=? AND status='queued' AND spec=?",
                    (now(), row["id"], row["spec"]),
                ).rowcount
            if changed == 1:
                return row
        return None

    def _consume(self) -> None:
        while not self.shutdown.is_set():
            row = self._claim_ready()
            if row:
                self._execute(row["id"])
            else:
                self.wake.wait(timeout=0.2)
                self.wake.clear()

    def _execute(self, job_id: str) -> None:
        spec: RunSpec | None = None
        outcome: PhaseResult | None = None
        try:
            spec = self._spec(job_id)
            original = self.store.project(spec.project_id)
            files, relative = self.store.locations.pdf_files(original)
            content = files.read(relative, max_bytes=128 * 1024 * 1024)
            if hashlib.sha256(content).hexdigest() != spec.sha256:
                raise WebError(
                    409,
                    "source_changed",
                    "Original PDF fingerprint changed; task was not started.",
                )
            del content
            deadline = time.monotonic() + self.timeout
            core_completed = False
            core_rejected = False
            if not spec.admet_only:
                checkpoints = LiveCheckpoints(
                    Path(spec.output_dir), spec.project_id, self.service.refresh
                )
                outcome = self.phases.run(spec, deadline, checkpoint=checkpoints.update)
                # This is the sole terminal core projection. Never re-project
                # after ADMET: doing so would invalidate its immutable source key.
                self.service.refresh(spec.project_id)
                core_rejected = (
                    spec.include_admet
                    and outcome.status == "failed"
                    and outcome.cleaned
                    and completed_qa_rejection(Path(spec.output_dir))
                )
                if (
                    outcome.status != "complete" and not core_rejected
                ) or not outcome.cleaned:
                    self._finish(
                        job_id,
                        outcome.status,
                        outcome.error,
                        clear_identity=outcome.cleaned,
                    )
                    return
                if not spec.include_admet:
                    self._finish(job_id, "complete", None)
                    return
                project = self.store.project(spec.project_id)
                snapshot = json.loads(project["snapshot"])
                if project["run_root"] != spec.output_dir or (
                    snapshot.get("acceptance", {}).get("state") != "accepted"
                    and not core_rejected
                ):
                    raise WebError(
                        409,
                        "core_not_accepted",
                        "Core extraction did not pass formal QA; ADMET was not started.",
                    )
                core_completed = True
            write_admet_stage(
                Path(spec.output_dir),
                self.store.job(job_id),
                Stage(name="admet"),
                core_completed=core_completed,
            )
            phase_spec = replace(spec, admet_only=True)
            outcome = self.phases.run(phase_spec, deadline)
            research_stage = None
            if outcome.status == "complete" and outcome.cleaned:
                research_stage = self._confirm_predictions(job_id, spec)
            self._finish(
                job_id,
                "failed"
                if core_rejected and outcome.status == "complete"
                else outcome.status,
                Error(
                    code="core_not_accepted",
                    message=(
                        "Qualified research values are available, but formal extraction QA requires review."
                        if research_stage is not None and research_stage.status == "ok"
                        else "No qualified research values were produced; formal extraction QA requires review."
                        if research_stage is not None
                        and research_stage.status == "empty"
                        else "Formal extraction QA requires review; research value availability is unconfirmed."
                    ),
                )
                if core_rejected and outcome.status == "complete"
                else outcome.error,
                clear_identity=outcome.cleaned,
            )
        except Exception as exc:
            logger.exception("Job %s failed at server boundary", job_id)
            error = (
                Error(code=exc.code, message=exc.message)
                if isinstance(exc, WebError)
                else Error(
                    code="job_internal",
                    message="Task failed at the local process boundary; inspect private run logs.",
                )
            )
            self._finish(
                job_id,
                "failed",
                error,
                clear_identity=outcome is None or outcome.cleaned,
            )

    @staticmethod
    def _phase_spec(spec: RunSpec, identity: ProcessIdentity) -> RunSpec:
        if (
            identity.phase not in {"extract", "admet"}
            or (identity.phase == "admet" and not spec.include_admet)
            or (identity.phase == "extract" and spec.admet_only)
        ):
            raise WebError(
                409, "invalid_process_record", "Persisted phase ownership is invalid."
            )
        return replace(spec, admet_only=True) if identity.phase == "admet" else spec

    def corrected(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        compound_id: str,
        compound,
    ) -> None:
        correction_prediction(self.store, connection, project_id, compound_id, compound)
        self.wake.set()

    def _confirm_predictions(self, job_id: str, spec: RunSpec) -> Stage:
        from .completion_inputs import completion_inputs
        from .correction_storage import correction_source_fingerprint
        from .prediction_identity import compound_prediction_eligible

        stage, core_completed = read_admet_stage(
            self.store.job(job_id), Path(spec.output_dir)
        )
        if (
            stage is None
            or stage.status not in {"ok", "empty"}
            or stage.progress is None
            or stage.progress.completed != stage.progress.total
            or (stage.status == "ok" and stage.progress.total < 1)
            or (stage.status == "empty" and stage.progress.total != 0)
            or stage.progress.failures
            or stage.count != stage.progress.completed
            or core_completed != (not spec.admet_only)
        ):
            raise WebError(
                502,
                "admet_incomplete",
                "The ADMET producer did not publish complete current stage evidence.",
            )
        project = self.store.project(spec.project_id)
        raw = {row["id"]: row for row in self.service.result_rows(spec.project_id)}
        selected = [
            compound
            for compound in self.service.effective_compounds(spec.project_id)
            if not spec.admet_compounds or compound.id in spec.admet_compounds
        ]
        if spec.admet_compounds and {compound.id for compound in selected} != set(
            spec.admet_compounds
        ):
            raise WebError(
                502,
                "admet_incomplete",
                "The selected source observations are no longer present.",
            )
        if completion_inputs(project, raw, selected):
            raise WebError(
                502,
                "admet_incomplete",
                "Proved numbered structures are still missing source-checked recognition.",
            )
        eligible = [
            compound for compound in selected if compound_prediction_eligible(compound)
        ]
        skipped = len(selected) - len(eligible)
        selected = eligible
        results = self.service.predictions.summaries(
            spec.project_id,
            [
                (
                    compound.id,
                    correction_source_fingerprint(project, raw[compound.id]),
                    compound.smiles,
                )
                for compound in selected
            ],
            molfiles={compound.id: compound.structure_molfile for compound in selected},
        )
        calculations = self.service.descriptors.summaries(
            spec.project_id,
            [
                (c.id, correction_source_fingerprint(project, raw[c.id]), c.smiles)
                for c in selected
            ],
            molfiles={c.id: c.structure_molfile for c in selected},
        )
        if (
            len(selected) != stage.progress.total
            or stage.skipped != skipped
            or len(results) != len(selected)
            or any(result.status != "complete" for result in results.values())
            or len(calculations) != len(selected)
            or any(result.status != "complete" for result in calculations.values())
            or sum(result.job_id != job_id for result in results.values())
            != stage.progress.cache_hits
        ):
            raise WebError(
                502,
                "admet_incomplete",
                "Source-bound predictions are missing or stale; task completion was withheld.",
            )
        self.service.leads.confirm(spec.project_id, job_id)
        return stage
