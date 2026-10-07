"""One bounded, deadline-aware JSONL carrier for the isolated OCSR process."""

from __future__ import annotations

import json
import math
import os
import selectors
import subprocess
import time

from .resource_budget import resident_budget_mb, worker_resident_mb


class WorkerProtocolError(RuntimeError):
    pass


def validate_observation_metadata(value: dict) -> None:
    peak = value.get("peak_rss_mb")
    if peak is not None and (
        type(peak) not in {int, float}
        or not math.isfinite(peak)
        or not 0 <= peak <= 1_000_000
    ):
        raise WorkerProtocolError("OCSR returned invalid memory telemetry")
    if value.get("device") not in {None, "cpu", "gpu"}:
        raise WorkerProtocolError("OCSR returned an unknown execution device")
    confidence = value.get("token_confidence")
    if confidence is not None and (
        not isinstance(confidence, dict)
        or set(confidence) != {"minimum", "mean"}
        or any(
            type(item) not in {int, float}
            or not math.isfinite(item)
            or not 0 <= item <= 1
            for item in confidence.values()
        )
        or confidence["minimum"] > confidence["mean"]
    ):
        raise WorkerProtocolError("OCSR returned invalid uncalibrated token confidence")


class JsonLineWorker:
    MAX_PACKET = 65536
    MAX_DIAGNOSTIC = 8192

    def __init__(self, command: list[str], environment: dict[str, str]):
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            bufsize=0,
        )
        self._selector = selectors.DefaultSelector()
        self._buffer = bytearray()
        self._diagnostic = bytearray()
        for stream in (self.process.stdout, self.process.stderr):
            os.set_blocking(stream.fileno(), False)
            self._selector.register(stream, selectors.EVENT_READ)

    @property
    def diagnostic(self) -> str:
        return self._diagnostic.decode("utf-8", errors="replace")[-2000:]

    def send(self, value: dict) -> None:
        packet = (
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            + b"\n"
        )
        if len(packet) > 4096:
            raise WorkerProtocolError("OCSR request exceeds the bounded protocol")
        self.process.stdin.write(packet)
        self.process.stdin.flush()

    def receive(self, timeout: float) -> dict:
        deadline = time.monotonic() + max(0.001, timeout)
        while True:
            resident = worker_resident_mb(self.process.pid)
            if resident is not None and resident > resident_budget_mb():
                raise WorkerProtocolError(
                    "OCSR worker exceeded its resident memory budget"
                )
            boundary = self._buffer.find(b"\n")
            if boundary >= 0:
                packet = bytes(self._buffer[:boundary])
                del self._buffer[: boundary + 1]
                try:
                    result = json.loads(packet.decode("utf-8"))
                except (ValueError, UnicodeError) as exc:
                    raise WorkerProtocolError("OCSR returned invalid JSON") from exc
                if not isinstance(result, dict):
                    raise WorkerProtocolError("OCSR returned a non-object packet")
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("OCSR protocol deadline exceeded")
            if not self._selector.get_map():
                raise WorkerProtocolError(
                    "OCSR closed its protocol before a complete response"
                )
            for key, _mask in self._selector.select(min(remaining, 0.2)):
                data = os.read(key.fd, 4096)
                if not data:
                    self._selector.unregister(key.fileobj)
                elif key.fileobj is self.process.stdout:
                    self._buffer.extend(data)
                    if len(self._buffer) > self.MAX_PACKET:
                        raise WorkerProtocolError(
                            "OCSR response exceeds the bounded protocol"
                        )
                else:
                    self._diagnostic.extend(data)
                    del self._diagnostic[: -self.MAX_DIAGNOSTIC]

    def close(self) -> None:
        process = self.process
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        finally:
            self._selector.close()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()


def query_identity(python: str, wrapper: str, environment: dict[str, str]) -> dict:
    worker = JsonLineWorker([python, wrapper, "--identity"], environment)
    try:
        identity = worker.receive(30)
        if identity.get("error"):
            raise WorkerProtocolError(str(identity["error"])[:500])
        fingerprint = identity.get("fingerprint")
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in fingerprint)
        ):
            raise WorkerProtocolError("OCSR did not provide a content fingerprint")
        return identity
    finally:
        worker.close()
