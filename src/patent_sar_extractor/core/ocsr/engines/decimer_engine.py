"""Single owned DECIMER process, explicit lifecycle and content identity."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path

from patent_sar_extractor.core.env_runner import (
    configured_model_environment,
    get_python,
)
from patent_sar_extractor.core.ocsr.worker_process import (
    JsonLineWorker,
    WorkerProtocolError,
    query_identity,
    validate_observation_metadata,
)
from patent_sar_extractor.core.runtime_env import build_gpu_env

from .base_engine import BaseOCSREngine

logger = logging.getLogger(__name__)
_WRAPPER = str(Path(__file__).resolve().parents[1] / "wrapper_decimer_batch.py")


class DECIMEREngine(BaseOCSREngine):
    name = "decimer"

    def __init__(
        self,
        python_bin: str | None = None,
        batch_wrapper_script: str | None = None,
        env_extra: dict[str, str] | None = None,
    ):
        self.python_bin = python_bin or get_python("decimer")
        self.batch_wrapper_script = batch_wrapper_script or os.environ.get(
            "DECIMER_BATCH_WRAPPER", _WRAPPER
        )
        self._worker: JsonLineWorker | None = None
        self._lock = threading.Lock()
        self._identity: dict | None = None
        self._starts = 0
        self._last_failure = ""
        self._identity_failure: str | None = None
        self._env_extra = dict(env_extra or {})

    @property
    def worker_process(self):
        return self._worker.process if self._worker else None

    def is_available(self) -> bool:
        return (
            Path(self.python_bin).is_file()
            and Path(self.batch_wrapper_script).is_file()
        )

    def _build_env(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.update(configured_model_environment())
        environment.update(self._env_extra)
        environment.setdefault("PATENTSAR_DECIMER_ENABLE_GPU", "0")
        environment.setdefault("PATENTSAR_DECIMER_CPU_THREADS", "2")
        if environment["PATENTSAR_DECIMER_ENABLE_GPU"] != "1":
            environment.update(
                CUDA_VISIBLE_DEVICES="-1",
                LD_PRELOAD="",
                LD_LIBRARY_PATH=str(Path(self.python_bin).parent.parent / "lib"),
            )
        else:
            environment = build_gpu_env(
                python_path=self.python_bin, base_env=environment
            )
        environment["TF_CPP_MIN_LOG_LEVEL"] = "2"
        return environment

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
        if self._worker and self._worker.process.poll() is None:
            return
        self._stop()
        if self._starts >= 2:
            raise WorkerProtocolError(
                "OCSR bounded process restart budget exhausted: " + self._last_failure
            )
        identity = self.runtime_identity()
        self._starts += 1
        self._worker = JsonLineWorker(
            [self.python_bin, self.batch_wrapper_script], self._build_env()
        )
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
                "DECIMER interpreter or JSONL worker is unavailable"
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
                        str(output.get("error", "DECIMER prediction failed"))[:500]
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
                            "device",
                            "peak_rss_mb",
                        )
                    },
                )
            except (TimeoutError, OSError, ValueError, WorkerProtocolError) as exc:
                self._last_failure = str(exc)[:500]
                diagnostic = self._worker.diagnostic if self._worker else ""
                logger.error(
                    "DECIMER worker stopped: %s; diagnostic=%s",
                    self._last_failure,
                    diagnostic,
                )
                self._stop()
                if isinstance(exc, TimeoutError):
                    return self._make_timeout_result(timeout)
                return self._make_failed_result(self._last_failure)
