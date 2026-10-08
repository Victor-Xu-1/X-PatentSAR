"""Explicit SAR-only queue on the shared owned-process and resource authorities."""

from __future__ import annotations

import json
import sqlite3
import threading

from ..analysis_process import BoundedAnalysisRunner
from ..errors import WebError
from .admission import existing, publish
from .engine import engine_identity
from .execution import execute
from .job_store import Jobs
from .models import AnalysisRequest, SARJob
from .ownership import absent
from .service import SARService


class SARQueue:
    def __init__(self, service: SARService):
        self.service = service
        self.jobs = Jobs(service.store)
        self.closed = threading.Event()
        self.wake = threading.Event()
        self.cancel_signal = threading.Event()
        self.active_id: str | None = None
        self.thread: threading.Thread | None = None
        self.runner: BoundedAnalysisRunner | None = None
        self.retained_lease = None
        self.recovery_blocked = False

    def start(self) -> None:
        with self.service.store.connect() as connection:
            unready = [
                item[0]
                for item in connection.execute(
                    "SELECT id FROM jobs WHERE status='queued' AND ready=0"
                )
            ]
        for identifier in unready:
            self.jobs.update(
                identifier,
                status="failed",
                error_code="sar_input_unpublished",
                error_message="Input preparation was interrupted; create a new explicit analysis.",
            )
        with self.service.store.connect() as connection:
            unfinished = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM jobs WHERE deleted=0 AND status!='queued'"
                )
            ]
        for row in unfinished:
            spec = json.loads(row["spec"])
            value = SARJob.model_validate_json(row["payload"])
            if (
                not value.started_at
                and value.status != "running"
                and value.error_code != "sar_process_unverified"
            ):
                continue
            safe = self.service.assets.job_files(row["root"], value.id)
            try:
                verified = absent(
                    safe, value.id, value.input_sha256, spec["attempt_id"]
                )
            except WebError:
                verified = False
            self.recovery_blocked = self.recovery_blocked or not verified
            if verified:
                self.jobs.cleaned(value.id, spec["attempt_id"])
                if (
                    value.status == "running"
                    or value.error_code == "sar_process_unverified"
                ):
                    self.jobs.update(
                        value.id,
                        status="interrupted",
                        error_code=None,
                        error_message=None,
                    )
            else:
                self.jobs.update(
                    value.id,
                    status="interrupted",
                    error_code="sar_process_unverified",
                    error_message="Previous SAR worker absence has not been verified.",
                )
        self.thread = threading.Thread(
            target=self._loop, name="patentsar-sar", daemon=True
        )
        self.thread.start()
        self.wake.set()

    def close(self) -> None:
        self.closed.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise WebError(
                    503, "sar_shutdown", "SAR worker shutdown has not been verified."
                )
        if self.runner:
            self.runner.close()
        if self.retained_lease:
            self.retained_lease.__exit__(None, None, None)
            self.retained_lease = None

    def enqueue(self, dataset_id: str, request: AnalysisRequest) -> SARJob:
        old, request_hash = existing(self, dataset_id, request)
        if old:
            return old
        dataset = self.service.current(dataset_id, request.expected_dataset_revision)
        region = self.service.datasets.region(request.region_id, dataset_id)
        if (
            region.kind != "variable"
            or region.dataset_revision != dataset.revision
            or not any(metric.id == request.metric_id for metric in dataset.metrics)
        ):
            raise WebError(
                422,
                "sar_analysis_parameters",
                "Metric or region is not from the current dataset.",
            )
        if any(not value or len(value) > 100 for value in request.grade_order) or len(
            set(request.grade_order)
        ) != len(request.grade_order):
            raise WebError(
                422,
                "sar_grade_order",
                "Grade order must contain distinct explicit labels, strongest first.",
            )
        molecules = self.service.datasets.all(dataset_id)
        if len(molecules) < 2:
            raise WebError(
                422,
                "sar_pool_small",
                "At least two source records are needed for comparison.",
            )
        return publish(
            self,
            dataset,
            molecules,
            request,
            request_hash,
            regions=[region],
            kind="reference",
            metric_id=request.metric_id,
        )

    def study(self, dataset_id: str, request) -> SARJob:
        from .study_admission import enqueue_study

        return enqueue_study(self, dataset_id, request)

    def view(self, identifier: str) -> SARJob:
        value = self.jobs.get(identifier)
        value.stale = self.service.dataset(value.dataset_id).stale
        row = self.jobs.record(identifier)
        if not row["ready"]:
            return value
        safe = self.service.assets.job_files(row["root"], identifier)
        progress = safe.json("progress.json")
        if (
            value.status in {"running", "interrupted", "failed", "cancelled"}
            and isinstance(progress, dict)
            and (
                progress.get("input_sha256") == value.input_sha256
                and type(progress.get("processed")) is int
                and type(progress.get("matched")) is int
                and 0 <= progress["matched"] <= progress["processed"] <= value.total
            )
        ):
            value.processed, value.matched = progress["processed"], progress["matched"]
        return value

    def resume(self, identifier: str, expected: str) -> SARJob:
        if self.active_id == identifier:
            raise WebError(
                409,
                "sar_active",
                "Wait for the current SAR attempt to finish cleanup before resuming.",
            )
        row = self.jobs.record(identifier)
        if not row["ready"]:
            raise WebError(
                409,
                "sar_input_unpublished",
                "This input was never published; create a new analysis.",
            )
        value = SARJob.model_validate_json(row["payload"])
        spec = json.loads(row["spec"])
        if expected != value.input_sha256 or spec["engine_sha256"] != engine_identity():
            raise WebError(
                409,
                "sar_resume_changed",
                "SAR input or algorithm changed; start a new analysis.",
            )
        self.service.current(value.dataset_id)
        safe = self.service.assets.job_files(row["root"], identifier)
        if value.started_at and not absent(
            safe, identifier, expected, spec["attempt_id"]
        ):
            raise WebError(
                409,
                "sar_process_unverified",
                "Previous worker cleanup must be verified before resuming.",
            )
        if self.retained_lease:
            raise WebError(
                409,
                "sar_process_unverified",
                "Current worker cleanup remains unverified.",
            )
        with self.service.store.connect() as connection:
            blocked = [
                dict(item)
                for item in connection.execute(
                    "SELECT * FROM jobs WHERE json_extract(payload,'$.error_code')='sar_process_unverified' OR (status NOT IN ('queued','running') AND json_extract(payload,'$.started_at') IS NOT NULL AND cleanup_verified=0)"
                )
            ]
        for other in blocked:
            saved = SARJob.model_validate_json(other["payload"])
            saved_spec = json.loads(other["spec"])
            other_files = self.service.assets.job_files(other["root"], saved.id)
            if not absent(
                other_files, saved.id, saved.input_sha256, saved_spec["attempt_id"]
            ):
                raise WebError(
                    409,
                    "sar_process_unverified",
                    "Another previous SAR worker still lacks verified cleanup.",
                )
        self.recovery_blocked = False
        value = self.jobs.resume(identifier)
        self.wake.set()
        return value

    def cancel(self, identifier: str) -> SARJob:
        value = self.jobs.cancel(identifier)
        if self.active_id == identifier:
            self.cancel_signal.set()
        return value

    def _loop(self) -> None:
        while not self.closed.is_set():
            if not self.wake.wait(timeout=1):
                continue
            self.wake.clear()
            if self.closed.is_set():
                return
            if self.retained_lease:
                continue
            if self.recovery_blocked:
                continue
            try:
                row = self.jobs.claim()
            except (sqlite3.Error, WebError, ValueError, OSError):
                # Storage corruption is an explicit module fault, never an idle retry loop.
                return
            if row:
                self._execute(row)
                self.wake.set()

    def _execute(self, row: dict) -> None:
        runner = BoundedAnalysisRunner(max_memory_bytes=512 * 1024 * 1024)
        self.runner = runner
        execute(self, row, runner)
