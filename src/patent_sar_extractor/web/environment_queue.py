"""Durable environment lifecycle; reuses verified process ownership and cancellation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .environment_models import EnvironmentComponent
from .environment_storage import EnvironmentStore
from .errors import WebError
from .files import SafeFiles, private_directory
from .processes import ProcessIdentity, ProcessRunner, RunSpec
from .storage import encode, now

logger = logging.getLogger(__name__)


class EnvironmentQueue:
    def __init__(
        self,
        store: EnvironmentStore,
        runner: ProcessRunner,
        timeout: float,
        completed: Callable[[dict[str, Any], dict[str, Any]], None],
        prepare: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.store, self.runner, self.timeout, self.completed = (
            store,
            runner,
            timeout,
            completed,
        )
        self.prepare = prepare
        self.stop_requested = threading.Event()
        self.wake = threading.Event()
        self.thread: threading.Thread | None = None
        self.cleanup_failure: WebError | None = None

    def start(self) -> None:
        self.reconcile()
        self.thread = threading.Thread(
            target=self._consume, name="patentsar-environment-queue", daemon=True
        )
        self.thread.start()

    def close(self) -> None:
        self.stop_requested.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=12)
            if self.thread.is_alive():
                raise WebError(
                    500,
                    "environment_shutdown",
                    "Environment worker shutdown was not verified.",
                )
        if self.cleanup_failure:
            raise self.cleanup_failure

    def spec(self, row: dict[str, Any]) -> tuple[RunSpec, dict[str, Any]]:
        identifier = row["id"]
        if (
            not isinstance(identifier, str)
            or len(identifier) != 32
            or any(c not in "0123456789abcdef" for c in identifier)
        ):
            raise WebError(
                409,
                "environment_record",
                "Environment operation identity is invalid; no process was touched.",
            )
        value = json.loads(row["spec"])
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or value.get("operation_id") != identifier
            or value.get("install_root") != row["install_root"]
            or value.get("action") != row["action"]
            or value.get("component_ids") != json.loads(row["component_ids"])
        ):
            raise WebError(
                409,
                "environment_record",
                "Environment operation specification is invalid; no process was touched.",
            )
        output = self.store.root / "operations" / identifier
        if output.is_symlink() or not output.resolve().is_relative_to(
            self.store.root / "operations"
        ):
            raise WebError(
                409,
                "environment_record",
                "Environment operation storage is unsafe; no process was touched.",
            )
        digest = hashlib.sha256(encode(value).encode()).hexdigest()
        return RunSpec(
            identifier, "environment", "", str(output), "environment", digest
        ), value

    def reconcile(self) -> None:
        for row in self.store.history(active_only=True):
            spec, _ = self.spec(row)
            if row["identity"]:
                try:
                    identity = ProcessIdentity(**json.loads(row["identity"]))
                except (TypeError, ValueError) as error:
                    raise WebError(
                        409,
                        "environment_record",
                        "Saved environment process ownership is invalid.",
                    ) from error
                if not self.runner.stop(identity, spec):
                    raise WebError(
                        409,
                        "environment_owner",
                        "Could not verify the previous environment worker's shutdown; no unrelated process was stopped.",
                    )
            self.store.update(
                row["id"],
                status="interrupted",
                finished_at=now(),
                stage="已中断，等待重新检测或重试",
                error=encode(
                    {
                        "code": "environment_interrupted",
                        "message": "Application restarted; incomplete installations were not activated.",
                    }
                ),
            )

    def _progress(self, spec: RunSpec) -> None:
        safe = SafeFiles(Path(spec.output_dir))
        progress = Path(spec.output_dir) / "environment-progress.json"
        if progress.exists():
            value = json.loads(safe.read(progress.name, max_bytes=65536))
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("stage"), str)
                or len(value["stage"]) > 200
                or not isinstance(value.get("completed_components", []), list)
            ):
                raise WebError(
                    500,
                    "environment_progress",
                    "Worker progress did not satisfy its bounded contract.",
                )
            completed = value.get("completed_components", [])
            if len(completed) > 6 or any(
                item
                not in {
                    "installer",
                    "base",
                    "decimer",
                    "decimer-models",
                    "admet",
                    "admet-models",
                }
                for item in completed
            ):
                raise WebError(
                    500, "environment_progress", "Worker component progress is invalid."
                )
            self.store.update(
                spec.job_id,
                stage=value["stage"],
                completed_components=encode(completed),
            )
        log = Path(spec.output_dir) / "web-process.log"
        if log.exists():
            with safe.open(log.name, max_bytes=8 * 1024 * 1024) as stream:
                stream.seek(max(0, os.fstat(stream.fileno()).st_size - 32768))
                lines = stream.read(32768).decode(errors="replace").splitlines()[-100:]
            self.store.update(
                spec.job_id, log_tail=encode([line[:1000] for line in lines])
            )

    def _result(self, spec: RunSpec, plan: dict[str, Any]) -> dict[str, Any]:
        raw = SafeFiles(Path(spec.output_dir)).read(
            "environment-result.json", max_bytes=512 * 1024
        )
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or value.get("operation_id") != spec.job_id
            or not isinstance(value.get("components"), list)
            or len(value["components"]) > 6
            or not isinstance(value.get("bindings"), dict)
        ):
            raise WebError(
                500,
                "environment_result",
                "Worker result did not satisfy its bounded operation contract.",
            )
        reports = [
            EnvironmentComponent.model_validate(item) for item in value["components"]
        ]
        ids = [report.id for report in reports]
        if len(ids) != len(set(ids)) or not set(plan["component_ids"]) <= set(ids):
            raise WebError(
                500,
                "environment_result",
                "Worker result is missing requested components.",
            )
        if plan["action"] == "install" and any(
            report.status != "ready"
            for report in reports
            if report.id in plan["component_ids"]
        ):
            raise WebError(
                500,
                "environment_verification",
                "Requested environments did not pass verification; no configuration was activated.",
            )
        return value

    def _run(self, row: dict[str, Any]) -> None:
        spec, plan = self.spec(row)
        if self.prepare:
            self.prepare(plan)
        output = private_directory(Path(spec.output_dir))
        plan_file = output / "environment-plan.json"
        descriptor = os.open(
            plan_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encode(plan))
            stream.flush()
            os.fsync(stream.fileno())
        identity = self.runner.start(spec)
        try:
            self._register(spec, plan, identity, output)
        except BaseException:
            if not self.runner.stop(identity, spec):
                raise WebError(
                    500,
                    "environment_shutdown",
                    "Unregistered environment worker shutdown was not verified.",
                )
            raise
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                latest = self.store.row(spec.job_id)
                if latest["cancel_requested"] or self.stop_requested.is_set():
                    if not self.runner.stop(identity, spec):
                        raise WebError(
                            500,
                            "environment_shutdown",
                            "Environment worker shutdown could not be verified.",
                        )
                    self.store.update(
                        spec.job_id,
                        status="interrupted"
                        if self.stop_requested.is_set()
                        else "cancelled",
                        finished_at=now(),
                        stage="已停止；未完成的环境不会启用",
                    )
                    return
                if time.monotonic() > deadline:
                    raise WebError(
                        504,
                        "environment_timeout",
                        "Environment operation exceeded its bounded lifetime.",
                    )
                code = self.runner.poll(identity, spec)
                self.store.update(spec.job_id, identity=encode(identity.to_dict()))
                self._progress(spec)
                if code is not None:
                    if not self.runner.stop(identity, spec):
                        raise WebError(
                            500,
                            "environment_shutdown",
                            "Environment worker descendants did not terminate safely.",
                        )
                    if code != 0:
                        raise WebError(
                            500,
                            "environment_install_failed",
                            "Environment operation failed; existing environments were preserved. Check the bounded installation log and retry after correcting the reported cause.",
                        )
                    result = self._result(spec, plan)
                    self.completed(plan, result)
                    self.store.update(
                        spec.job_id,
                        status="complete",
                        finished_at=now(),
                        stage="检测完成"
                        if plan["action"] == "inspect"
                        else "安装与配置校验完成",
                        completed_components=encode(plan["component_ids"]),
                    )
                    return
                self.stop_requested.wait(0.2)
        finally:
            if not self.runner.stop(identity, spec):
                raise WebError(
                    500,
                    "environment_shutdown",
                    "Environment process cleanup was not verified.",
                )

    def _consume(self) -> None:
        while not self.stop_requested.is_set():
            queued = [
                row
                for row in self.store.history(active_only=True)
                if row["status"] == "queued"
            ]
            if not queued:
                self.wake.wait(0.5)
                self.wake.clear()
                continue
            row = queued[0]
            try:
                if row["cancel_requested"]:
                    self.store.update(
                        row["id"],
                        status="cancelled",
                        finished_at=now(),
                        stage="已取消，尚未执行",
                    )
                else:
                    self._run(row)
            except Exception as error:
                logger.error(
                    "environment_operation_failed operation=%s error_type=%s",
                    row["id"],
                    type(error).__name__,
                )
                payload = (
                    error.payload()["error"]
                    if isinstance(error, WebError)
                    else {
                        "code": "environment_failed",
                        "message": "Environment operation failed safely; no partial result was reported as ready.",
                    }
                )
                self.store.update(
                    row["id"],
                    status="failed",
                    finished_at=now(),
                    error=encode(payload),
                    stage="失败；现有环境保持不变",
                )
                if isinstance(error, WebError) and error.code == "environment_shutdown":
                    self.cleanup_failure = error
                    self.stop_requested.set()

    def _register(
        self,
        spec: RunSpec,
        plan: dict[str, Any],
        identity: ProcessIdentity,
        output: Path,
    ) -> None:
        self.store.update(
            spec.job_id,
            status="running",
            started_at=now(),
            identity=encode(identity.to_dict()),
            stage="执行环境检测"
            if plan["action"] == "inspect"
            else "执行已固定的安装计划",
        )
        acknowledgement = {
            "operation_id": spec.job_id,
            "pid": identity.pid,
            "start_ticks": identity.start_ticks,
            "boot_id": identity.boot_id,
        }
        pending = output / "environment-owner.pending.json"
        descriptor = os.open(
            pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encode(acknowledgement))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, output / "environment-owner.json")
