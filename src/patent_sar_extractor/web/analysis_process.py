"""Single-consumer, bounded JSON subprocess transport with explicit cancellation."""

from __future__ import annotations

import json
import logging
import math
import os
import selectors
import subprocess
import threading
import time
from pathlib import Path
from typing import IO, cast

from .analysis_children import Children, read_child
from .errors import WebError
from .storage import encode

logger = logging.getLogger(__name__)
MAX_INPUT = 128 * 1024
MAX_STDOUT = 1024 * 1024
MAX_STDERR = 256 * 1024


class BoundedAnalysisRunner:
    def __init__(self, *, max_memory_bytes: int = 4608 * 1024 * 1024) -> None:
        if (
            isinstance(max_memory_bytes, bool)
            or not 1024 * 1024 <= max_memory_bytes <= 5 * 1024**3
        ):
            raise WebError(
                400,
                "analysis_memory_limit",
                "Analysis resident-memory limit must be between 1 MiB and 5 GiB.",
            )
        self.max_memory_bytes = max_memory_bytes
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._idle = threading.Event()
        self._idle.set()

    def close(self) -> None:
        self._closed.set()
        if not self._idle.wait(3):
            raise WebError(
                503,
                "analysis_shutdown",
                "Owned analysis is still stopping; shutdown was not verified.",
            )

    def run(
        self,
        command: list[str],
        payload: object,
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        cancel: threading.Event | None = None,
    ) -> dict[str, object]:
        if not math.isfinite(timeout) or not 0.05 <= timeout <= 180:
            raise WebError(
                400,
                "analysis_timeout",
                "Analysis must have a bounded lifetime of at most 180 seconds.",
            )
        data = encode(payload).encode()
        if len(data) > MAX_INPUT:
            raise WebError(
                413,
                "analysis_input_limit",
                "Analysis request exceeds its subprocess limit.",
            )
        if not self._lock.acquire(blocking=False):
            raise WebError(
                503,
                "analysis_busy",
                "Another local molecular analysis is running; retry after it finishes.",
            )
        self._idle.clear()
        started = time.monotonic()
        try:
            self._check_cancel(cancel)
            result = self._run(command, data, cwd, env, timeout, cancel)
            logger.info(
                "analysis_worker_complete duration_seconds=%.3f",
                time.monotonic() - started,
            )
            return result
        except WebError as exc:
            logger.warning(
                "analysis_worker_failed code=%s duration_seconds=%.3f",
                exc.code,
                time.monotonic() - started,
            )
            raise
        finally:
            self._idle.set()
            self._lock.release()

    def _check_cancel(self, cancel: threading.Event | None) -> None:
        if self._closed.is_set() or (cancel is not None and cancel.is_set()):
            raise WebError(
                503,
                "analysis_cancelled",
                "Local analysis was cancelled; no partial result was cached.",
            )

    def _run(
        self,
        command: list[str],
        data: bytes,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        cancel: threading.Event | None,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        try:
            child = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise WebError(
                503,
                "analysis_environment_unavailable",
                "Local analysis interpreter could not start.",
            ) from exc
        selector = selectors.DefaultSelector()
        owner: Children | None = None
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        try:
            raw = read_child(child.pid)
            if raw is None:
                # Still our direct, unreaped Popen; never signal an arbitrary PID.
                if child.poll() is None:
                    child.kill()
                raise WebError(
                    502,
                    "analysis_start_failed",
                    "Analysis exited before process ownership could be verified.",
                )
            owner = Children(raw, self.max_memory_bytes)
            assert (
                child.stdin is not None
                and child.stdout is not None
                and child.stderr is not None
            )
            for stream, label, event in (
                (child.stdin, "stdin", selectors.EVENT_WRITE),
                (child.stdout, "stdout", selectors.EVENT_READ),
                (child.stderr, "stderr", selectors.EVENT_READ),
            ):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, event, label)
            pending = memoryview(data)
            while selector.get_map() or child.poll() is None:
                self._check_cancel(cancel)
                owner.observe()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WebError(
                        504,
                        "analysis_timeout",
                        "Local molecular analysis exceeded its time limit.",
                    )
                for key, _ in selector.select(min(0.05, remaining)):
                    stream = cast(IO[bytes], key.fileobj)
                    if key.data == "stdin":
                        try:
                            count = os.write(stream.fileno(), pending)
                        except BrokenPipeError:
                            pending = memoryview(b"")
                        except BlockingIOError:
                            continue
                        else:
                            pending = pending[count:]
                        if not pending:
                            selector.unregister(stream)
                            stream.close()
                    else:
                        try:
                            chunk = os.read(stream.fileno(), 65536)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(stream)
                            stream.close()
                            continue
                        buffer = buffers[key.data]
                        limit = MAX_STDOUT if key.data == "stdout" else MAX_STDERR
                        if len(buffer) + len(chunk) > limit:
                            raise WebError(
                                502,
                                "analysis_output_limit",
                                "Analysis output exceeded its safety limit.",
                            )
                        buffer.extend(chunk)
            if child.wait(timeout=1) != 0:
                raise WebError(
                    502,
                    "analysis_worker_failed",
                    "Local model failed; check the verified model environment.",
                )
            return _response(bytes(buffers["stdout"]))
        finally:
            selector.close()
            if owner is not None:
                owner.stop()
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)
            for opened_stream in (child.stdin, child.stdout, child.stderr):
                if opened_stream is not None:
                    opened_stream.close()


def _response(data: bytes) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"), parse_constant=_invalid_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise WebError(
            502,
            "analysis_protocol",
            "Local model returned malformed or non-finite JSON.",
        ) from exc
    if not isinstance(value, dict) or type(value.get("ok")) is not bool:
        raise WebError(
            502,
            "analysis_protocol",
            "Local model returned an invalid protocol envelope.",
        )
    if value["ok"] is False:
        code = value.get("code")
        if code in {"runtime_unavailable", "model_invalid"}:
            raise WebError(
                503,
                "analysis_environment_unavailable",
                "Verified analysis environment or model is unavailable.",
            )
        raise WebError(
            502,
            "analysis_worker_failed",
            "Local model could not produce a valid result.",
        )
    if set(value) != {"ok", "result"} or not isinstance(value["result"], dict):
        raise WebError(
            502, "analysis_protocol", "Local model returned an invalid result envelope."
        )
    return value["result"]


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-finite worker output")
