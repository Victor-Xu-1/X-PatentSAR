"""Bounded binary pipe collection for the existing Linux/WSL environment runner."""

from __future__ import annotations

import os
import selectors
import subprocess
import time
from collections.abc import Callable

OUTPUT_LIMIT = 65_536
_READ_SIZE = 4096
_OMITTED = b"\n[worker output truncated; original head and tail retained]\n"


class _Excerpt:
    """Never retain an unbounded line, stream, or temporary concatenation."""

    def __init__(self):
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def append(self, data: bytes) -> None:
        self.total += len(data)
        missing = OUTPUT_LIMIT // 3 - len(self.head)
        if missing:
            self.head.extend(data[:missing])
            data = data[missing:]
        self.tail.extend(data)
        del self.tail[: -(OUTPUT_LIMIT - OUTPUT_LIMIT // 3)]

    def value(self) -> bytes:
        marker = _OMITTED if self.total > OUTPUT_LIMIT else b""
        return bytes(self.head) + marker + bytes(self.tail)


class _Lines:
    """Bound each printable line before filtering/emitting progress."""

    def __init__(self, sink: Callable[[str], None], keep: Callable[[str], bool]):
        self.sink, self.keep = sink, keep
        self.pending = _Excerpt()
        self.suppressed = False
        self.probe = b""

    def append(self, data: bytes) -> None:
        for part in data.splitlines(keepends=True):
            # Tokens can straddle reads or disappear from a truncated middle.
            self.suppressed |= not self.keep(
                (self.probe + part).decode("utf-8", errors="replace")
            )
            self.probe = (self.probe + part)[-512:]
            self.pending.append(part)
            if part.endswith((b"\n", b"\r")):
                self.flush()

    def flush(self) -> None:
        if self.pending.total and not self.suppressed:
            self.sink(self.pending.value().decode("utf-8", errors="replace"))
        self.pending, self.probe, self.suppressed = _Excerpt(), b"", False


def run_bounded(
    cmd: list[str],
    *,
    timeout: float | None,
    cwd: str | None,
    env: dict[str, str] | None,
    on_line: Callable[[str], None] | None = None,
    keep_line: Callable[[str], bool] = lambda line: bool(line),
) -> subprocess.CompletedProcess[str]:
    """Drain both pipes without blocking on a newline; preserve caller ownership.

    Small stdout/stderr responses remain complete. Large diagnostic responses
    retain bounded original head/tail, with explicit truncation. Streaming keeps
    the existing merged stderr/stdout contract. No new session/process group is
    created: the existing parent-owned process carrier still owns descendants.
    Timeout/cancellation always kill and reap this exact Popen child, not peers.
    """
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if on_line else subprocess.PIPE,
            bufsize=0,
        )
    except BaseException:
        selector.close()
        raise
    captured = {"stdout": _Excerpt(), "stderr": _Excerpt()}
    lines = _Lines(on_line, keep_line) if on_line else None
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        for name in captured:
            stream = getattr(process, name)
            if stream is not None:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout)
            for key, _ in selector.select(
                0.1 if remaining is None else min(0.1, remaining)
            ):
                try:
                    data = os.read(key.fd, _READ_SIZE)
                except BlockingIOError:
                    continue
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                captured[key.data].append(data)
                if lines is not None:
                    lines.append(data)
        remaining = None if deadline is None else max(0, deadline - time.monotonic())
        process.wait(timeout=remaining)
        if lines is not None:
            lines.flush()
        return subprocess.CompletedProcess(
            cmd,
            process.returncode,
            captured["stdout"].value().decode("utf-8", errors="replace"),
            captured["stderr"].value().decode("utf-8", errors="replace"),
        )
    except subprocess.TimeoutExpired as error:
        error.output = captured["stdout"].value()
        error.stderr = captured["stderr"].value() if lines is None else None
        raise
    finally:
        try:
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            process.wait(timeout=2)
        finally:
            selector.close()
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
