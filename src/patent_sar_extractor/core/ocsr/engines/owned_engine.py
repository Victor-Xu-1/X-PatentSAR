"""One bounded owned JSONL lifecycle shared by native OCSR adapters."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path

from patent_sar_extractor.core.ocsr.resource_budget import resident_budget_mb
from patent_sar_extractor.core.ocsr.worker_process import (
    JsonLineWorker,
    WorkerProtocolError,
    query_identity,
    validate_observation_metadata,
)
from patent_sar_extractor.resource_admission import wait_for_memory

from .base_engine import BaseOCSREngine

logger = logging.getLogger(__name__)


class OwnedOCSREngine(BaseOCSREngine):
    memory_headroom_mb = 3072

    def __init__(
        self,
        python_bin: str,
        batch_wrapper_script: str,
        env_extra: dict[str, str] | None = None,
    ):
        self.python_bin = python_bin
        self.batch_wrapper_script = batch_wrapper_script
        self._worker: JsonLineWorker | None = None
        self._lock = threading.Lock()
        self._identity: dict | None = None
        self._starts = 0
        self._requests = 0
        self._worker_started = 0.0
        self._last_failure = ""
        self._identity_failure: str | None = None
        self._env_extra = dict(env_extra or {})

    @property
    def worker_process(self):
        return self._worker.process if self._worker else None

    @property
    def session_exhausted(self) -> bool:
        return bool(
            self._identity_failure or (self._starts >= 2 and self._worker is None)
        )

    def is_available(self) -> bool:
        return (
            Path(self.python_bin).is_file()
            and Path(self.batch_wrapper_script).is_file()
        )

    def _build_env(self) -> dict[str, str]:
        raise NotImplementedError

    def runtime_identity(self) -> dict:
        if self._identity_failure:
            raise WorkerProtocolError(self._identity_failure)
        if self._identity is None:
            try:
                self._identity = query_identity(
                    self.python_bin, self.batch_wrapper_script, self._build_env()
                )
            except (OSError, TimeoutError, ValueError, WorkerProtocolError) as exc:
                self._identity_failure = str(exc)[:500]
                raise
        return self._identity

    def _start(self) -> None:
        if (
            self._worker
            and self._worker.process.poll() is None
            and self._requests < 100
            and time.monotonic() - self._worker_started < 900
        ):
            return
        self._stop()
        if self._starts >= 2:
            raise WorkerProtocolError(
                "OCSR bounded process restart budget exhausted: " + self._last_failure
            )
        identity = self.runtime_identity()
        # A transient shortage is bounded waiting, not a consumed model restart.
        wait_for_memory(min(resident_budget_mb(), self.memory_headroom_mb))
        self._starts += 1
        self._worker = JsonLineWorker(
            [self.python_bin, self.batch_wrapper_script], self._build_env()
        )
        self._requests, self._worker_started = 0, time.monotonic()
        ready = self._worker.receive(120)
        if (
            ready.get("status") != "ready"
            or not isinstance(ready.get("identity"), dict)
            or ready["identity"].get("fingerprint") != identity["fingerprint"]
        ):
            raise WorkerProtocolError(
                "OCSR startup failed or model identity changed: "
                + str(ready.get("error", "invalid handshake"))[:500]
            )

    def _stop(self) -> None:
        worker, self._worker = self._worker, None
        if worker:
            worker.close()

    def close(self) -> None:
        with self._lock:
            self._stop()

    def predict(self, image_path: str, timeout: float = 60) -> dict:
        if not Path(image_path).is_file():
            return self._make_failed_result("OCSR input image is missing")
        if not self.is_available():
            return self._make_unavailable_result(
                "OCSR interpreter or JSONL worker is unavailable"
            )
        with self._lock:
            started = time.monotonic()
            try:
                self._start()
                request_id = uuid.uuid4().hex
                self._worker.send({"id": request_id, "image_path": image_path})
                output = self._worker.receive(timeout)
                if output.get("id") != request_id:
                    raise WorkerProtocolError("OCSR response request ID mismatch")
                if output.get("status") != "success":
                    return self._make_failed_result(
                        str(output.get("error", "Native OCSR prediction failed"))[:500]
                    )
                smiles = output.get("smiles")
                if (
                    not isinstance(smiles, str)
                    or not smiles.strip()
                    or len(smiles) > 12000
                ):
                    raise WorkerProtocolError("OCSR response has no bounded raw SMILES")
                if (
                    output.get("model_fingerprint")
                    != self.runtime_identity()["fingerprint"]
                ):
                    raise WorkerProtocolError(
                        "OCSR prediction model fingerprint mismatch"
                    )
                validate_observation_metadata(output)
                self._requests += 1
                self._starts = (
                    0  # A genuine protocol success restores the bounded restart budget.
                )
                return self._make_result(
                    status="success",
                    raw_smiles=smiles,
                    elapsed_sec=time.monotonic() - started,
                    **{
                        key: output.get(key)
                        for key in (
                            "model_fingerprint",
                            "model_version",
                            "token_confidence",
                            "model_confidence",
                            "device",
                            "peak_rss_mb",
                        )
                    },
                )
            except (TimeoutError, OSError, ValueError, WorkerProtocolError) as exc:
                self._last_failure = str(exc)[:500]
                diagnostic = self._worker.diagnostic if self._worker else ""
                logger.error(
                    "OCSR worker stopped: %s; diagnostic=%s",
                    self._last_failure,
                    diagnostic,
                )
                self._stop()
                if isinstance(exc, TimeoutError):
                    return self._make_timeout_result(timeout)
                return self._make_failed_result(self._last_failure)
