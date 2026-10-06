"""Lazy, task-owned JSONL model window with bounded recycling and cleanup."""

from __future__ import annotations

import math
import os
import selectors
import subprocess
import threading
import time
from pathlib import Path
from typing import IO, cast

from .analysis_children import Children, read_child
from .analysis_process import MAX_INPUT, MAX_STDERR, MAX_STDOUT, _response
from .errors import WebError
from .storage import encode


class ModelSession:
    def __init__(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        max_requests: int = 5,
        max_memory_bytes: int = 4608 * 1024**2,
        shutdown: threading.Event | None = None,
    ):
        if (
            not 1 <= max_requests <= 10
            or not 1024**2 <= max_memory_bytes <= 5 * 1024**3
        ):
            raise ValueError("Model window exceeds its reviewed resource limits")
        self.command, self.cwd, self.env = command, cwd, env
        self.max_requests, self.max_memory_bytes = max_requests, max_memory_bytes
        self.child: subprocess.Popen | None = None
        self.owner: Children | None = None
        self.requests = 0
        self.started = 0.0
        self.closed = False
        self.shutdown = shutdown
        self.cancel: threading.Event | None = None

    def is_set(self):
        return (
            self.closed
            or (self.shutdown is not None and self.shutdown.is_set())
            or (self.cancel is not None and self.cancel.is_set())
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _start(self, deadline: float):
        from patent_sar_extractor.resource_admission import wait_for_memory

        remaining = deadline - time.monotonic()
        if remaining < 0.05:
            raise WebError(
                504, "analysis_timeout", "Model budget expired before loading."
            )
        wait_for_memory(
            min(self.max_memory_bytes / 1024**2, 3072),
            cancel=self,
            timeout=min(110, remaining),
        )
        if time.monotonic() >= deadline:
            raise WebError(
                504,
                "analysis_timeout",
                "Model budget expired while awaiting resources.",
            )
        self.child = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        raw = read_child(self.child.pid)
        if raw is None:
            raise WebError(
                502, "analysis_start_failed", "Model ownership could not be verified."
            )
        self.owner = Children(raw, self.max_memory_bytes)
        self.requests, self.started = 0, time.monotonic()

    def _stop(self):
        child = self.child
        if child is None:
            return
        # Reuse the existing verified descendant cleanup authority.
        from .analysis_process import BoundedAnalysisRunner

        cleanup = BoundedAnalysisRunner(max_memory_bytes=self.max_memory_bytes)
        cleanup._stop_owned(child, self.owner)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                stream.close()
        self.child, self.owner = None, None

    def close(self):
        self.closed = True
        self._stop()

    def exchange(
        self, payload: object, *, timeout: float, cancel: threading.Event | None = None
    ) -> dict[str, object]:
        if not math.isfinite(timeout) or not 0.05 <= timeout <= 180:
            raise WebError(
                400, "analysis_timeout", "A model request needs a bounded timeout."
            )
        self.cancel = cancel
        if self.is_set():
            raise WebError(503, "analysis_cancelled", "Model window was cancelled.")
        data = encode(payload).encode() + b"\n"
        deadline = time.monotonic() + timeout
        if len(data) > MAX_INPUT:
            raise WebError(
                413, "analysis_input_limit", "Model request exceeds its limit."
            )
        if self.child is not None and (
            self.requests >= self.max_requests or time.monotonic() - self.started >= 150
        ):
            self._stop()
        try:
            if self.child is None:
                self._start(deadline)
            result = self._exchange(data, deadline, cancel)
            self.requests += 1
            return result
        except Exception:
            self.close()  # No retry, desynchronized session or overlapping model.
            raise

    def _exchange(self, data: bytes, deadline: float, cancel) -> dict[str, object]:
        child, owner = self.child, self.owner
        assert child is not None and owner is not None
        assert (
            child.stdin is not None
            and child.stdout is not None
            and child.stderr is not None
        )
        pending = memoryview(data)
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        with selectors.DefaultSelector() as selector:
            for stream, label, event in (
                (child.stdin, "stdin", selectors.EVENT_WRITE),
                (child.stdout, "stdout", selectors.EVENT_READ),
                (child.stderr, "stderr", selectors.EVENT_READ),
            ):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, event, label)
            while True:
                if self.is_set():
                    raise WebError(
                        503, "analysis_cancelled", "Model window was cancelled."
                    )
                owner.observe()
                if time.monotonic() >= deadline:
                    raise WebError(
                        504,
                        "analysis_timeout",
                        "Model request exceeded its time limit.",
                    )
                if child.poll() is not None:
                    raise WebError(
                        502, "analysis_worker_failed", "Owned model process stopped."
                    )
                for key, _ in selector.select(min(0.05, deadline - time.monotonic())):
                    stream = cast(IO[bytes], key.fileobj)
                    if key.data == "stdin":
                        try:
                            pending = pending[os.write(stream.fileno(), pending) :]
                        except BlockingIOError:
                            continue
                        if not pending:
                            selector.unregister(stream)
                        continue
                    try:
                        chunk = os.read(stream.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        raise WebError(
                            502, "analysis_protocol", "Model protocol stream closed."
                        )
                    buffer = buffers[key.data]
                    buffer.extend(chunk)
                    if len(buffer) > (
                        MAX_STDOUT if key.data == "stdout" else MAX_STDERR
                    ):
                        raise WebError(
                            502,
                            "analysis_output_limit",
                            "Model output exceeds its limit.",
                        )
                    if key.data == "stdout" and b"\n" in buffer:
                        if (
                            pending
                            or buffer.count(b"\n") != 1
                            or not buffer.endswith(b"\n")
                        ):
                            raise WebError(
                                502, "analysis_protocol", "Unsolicited model response."
                            )
                        return _response(bytes(buffer))
