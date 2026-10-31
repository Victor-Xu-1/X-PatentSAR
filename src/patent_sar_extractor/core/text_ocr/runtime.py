"""Serial task-owned auxiliary OCR, lazy models and bounded exact-input reuse."""

from __future__ import annotations

import hashlib
import math
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PIL import Image

from patent_sar_extractor.core.ocsr.worker_process import (
    JsonLineWorker,
    WorkerProtocolError,
)
from patent_sar_extractor.resource_admission import wait_for_memory

from .control import (
    STARTUP_SECONDS,
    control_packet,
    validate_prepared,
    worker_ready_matches,
)
from .process import (
    TextOCRCancelled,
    TextOCRPhaseTimeout,
    environment,
    model_stamp,
    query_text_identity,
    receive,
    remaining,
)
from .protocol import MAX_RSS_MB, frame_digest, validate_reply


class AuxiliaryTextRuntime:
    """One owner's finite session, not a service or a second extraction pipeline."""

    def __init__(self, python: Path, models: Path, workspace: Path, *, cancel=None):
        if (
            not python.is_absolute()
            or not python.is_file()
            or not models.is_absolute()
            or not workspace.is_absolute()
        ):
            raise ValueError(
                "Auxiliary text OCR requires explicit absolute runtime paths"
            )
        self.python, self.models, self.cancel = python, models, cancel
        self._temporary = tempfile.TemporaryDirectory(prefix="text-ocr-", dir=workspace)
        self.root = Path(self._temporary.name)
        self._env = environment(models, self.root)
        self._script = Path(__file__).with_name("worker.py")
        self._identity = None
        self._stamp = None
        self._worker = None
        self._model_prepared = False
        self._cache = OrderedDict()
        self._lock = threading.Lock()
        self._closed = False
        self._failures = self._requests = self._total = 0
        self._last_used = 0.0
        self.last_diagnostic = ""

    def _stop(self):
        worker, self._worker = self._worker, None
        self._model_prepared = False
        if worker is not None:
            worker.close()

    def close(self):
        with self._lock:
            self._stop()
            self._cache.clear()
            self._closed = True
            self._temporary.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def worker_process(self):
        return self._worker.process if self._worker else None

    def _prepare(self, deadline):
        stamp = model_stamp(self.models)
        if stamp != self._stamp:
            self._stop()
            self._cache.clear()
            self._identity = None
            identity = query_text_identity(
                [str(self.python), str(self._script)],
                self._env,
                self.models,
                deadline,
                self.cancel,
            )
            if model_stamp(self.models) != stamp:
                raise WorkerProtocolError(
                    "Auxiliary text OCR model changed during verification"
                )
            self._identity, self._stamp = identity, stamp

    def _start(self, deadline):
        if self._worker and (
            self._requests >= 256
            or time.monotonic() - self._last_used > 30
            or self._worker.process.poll() is not None
        ):
            self._stop()
        if self._worker:
            return
        budget = remaining(deadline, self.cancel)
        wait_for_memory(
            MAX_RSS_MB, timeout=max(0.05, min(10, budget)), cancel=self.cancel
        )
        remaining(deadline, self.cancel)
        self._worker = JsonLineWorker([str(self.python), str(self._script)], self._env)
        ready = receive(self._worker, deadline, self.cancel)
        if not worker_ready_matches(ready, self._identity):
            raise WorkerProtocolError("Auxiliary text OCR changed identity at startup")
        self._requests = 0

    def observe(self, image: np.ndarray, *, timeout=30) -> dict:
        pixel_digest = frame_digest(image)
        if (
            type(timeout) not in {int, float}
            or not math.isfinite(timeout)
            or not 1 <= timeout <= 60
        ):
            raise ValueError("Auxiliary text OCR requires a bounded request deadline")
        deadline = time.monotonic() + timeout
        try:
            while not self._lock.acquire(
                timeout=min(0.1, remaining(deadline, self.cancel))
            ):
                pass
        except TextOCRCancelled:
            # Cancellation may arrive between calls, including before a cache
            # hit. The prior loaded child still belongs to this cancelled owner.
            self.close()
            raise
        except TimeoutError as error:
            # A queued caller must not stop another call's owned worker.
            raise TextOCRPhaseTimeout("queue") from error
        path = None
        phase = "identity"
        try:
            if self._closed or self._failures >= 2 or self._total >= 2048:
                raise WorkerProtocolError(
                    "Auxiliary text OCR session is closed or exhausted"
                )
            # One finite activation budget includes identity, transport and
            # validated-row model loading. It is not an inference retry.
            deadline = time.monotonic() + STARTUP_SECONDS
            self._prepare(deadline)
            remaining(deadline, self.cancel)
            key = self._identity["fingerprint"], pixel_digest
            if key in self._cache:
                self._cache.move_to_end(key)
                return dict(self._cache[key], cache_hit=True)
            phase = "worker_ready"
            self._start(deadline)
            phase = "source_frame"
            with tempfile.NamedTemporaryFile(
                dir=self.root, suffix=".png", delete=False
            ) as stream:
                path = Path(stream.name)
                Image.fromarray(image).save(stream, format="PNG")
            request = {
                "id": uuid.uuid4().hex,
                "image_path": str(path),
                "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "pixel_sha256": pixel_digest,
                "shape": list(image.shape),
                "model_fingerprint": key[0],
            }
            remaining(deadline, self.cancel)
            if not self._model_prepared:
                phase = "model_prepare"
                remaining(deadline, self.cancel)
                self._requests += 1
                self._worker.send(control_packet("prepare", request))
                validate_prepared(receive(self._worker, deadline, self.cancel), request)
                self._model_prepared = True
                # Preparation consumes one of the same256 wire-command slots;
                # the2048 limit below counts inference attempts, not successes.
            remaining(deadline, self.cancel)
            if model_stamp(self.models) != self._stamp:
                raise WorkerProtocolError(
                    "Auxiliary text OCR model changed during preparation"
                )
            remaining(deadline, self.cancel)
            phase = "inference"
            deadline = time.monotonic() + timeout
            remaining(deadline, self.cancel)
            self._requests += 1
            self._total += 1
            self._worker.send(control_packet("observe", request))
            result = validate_reply(
                receive(self._worker, deadline, self.cancel), request
            )
            self._failures = 0
            self._last_used = time.monotonic()
            self._cache[key] = result
            while len(self._cache) > 128:
                self._cache.popitem(last=False)
            return dict(result, cache_hit=False)
        except (
            OSError,
            ValueError,
            TimeoutError,
            WorkerProtocolError,
            TextOCRCancelled,
        ) as error:
            self._failures += 1
            if self._worker is not None:
                self.last_diagnostic = getattr(self._worker, "diagnostic", "")[-2000:]
            self._stop()
            if isinstance(error, TimeoutError) and not isinstance(
                error, TextOCRPhaseTimeout
            ):
                raise TextOCRPhaseTimeout(phase) from error
            raise
        finally:
            try:
                if path is not None:
                    path.unlink(missing_ok=True)
            except OSError:
                self._stop()
                self._cache.clear()
                self._closed = True
                raise
            finally:
                self._lock.release()
