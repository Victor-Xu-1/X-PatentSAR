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

from .process import (
    TextOCRCancelled,
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
        self._cache = OrderedDict()
        self._lock = threading.Lock()
        self._closed = False
        self._failures = self._requests = self._total = 0
        self._last_used = 0.0
        self.last_diagnostic = ""

    def _stop(self):
        worker, self._worker = self._worker, None
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
        if ready != {"status": "ready", "identity": self._identity}:
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
        path = None
        try:
            if self._closed or self._failures >= 2 or self._total >= 2048:
                raise WorkerProtocolError(
                    "Auxiliary text OCR session is closed or exhausted"
                )
            self._prepare(deadline)
            remaining(deadline, self.cancel)
            key = self._identity["fingerprint"], pixel_digest
            if key in self._cache:
                self._cache.move_to_end(key)
                return dict(self._cache[key], cache_hit=True)
            self._start(deadline)
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
            self._worker.send(request)
            result = validate_reply(
                receive(self._worker, deadline, self.cancel), request
            )
            self._requests += 1
            self._total += 1
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
        ):
            self._failures += 1
            if self._worker is not None:
                self.last_diagnostic = getattr(self._worker, "diagnostic", "")[-2000:]
            self._stop()
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
