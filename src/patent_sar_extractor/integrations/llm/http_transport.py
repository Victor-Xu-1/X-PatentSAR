"""One owned Linux HTTP carrier; policy, retries, parsing and cache stay in client.

The worker performs exactly one request. Private stdin carries credentials and
payload; stdout is bounded transport data only. The caller owns the absolute
deadline and reaps only its Popen child, without a background thread or fallback.
"""

from __future__ import annotations

import base64
import ctypes
import json as wire_json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Protocol

import requests

if __package__ in {None, ""}:
    # -I excludes PYTHONPATH; only this exact trusted package source is admitted.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from patent_sar_extractor.integrations.llm.external_api import (
    PublicHTTPSConnection,
    validate_external_endpoint,
)

MAX_INPUT_BYTES = 512 * 1024
MAX_BODY_BYTES = 512 * 1024
POLL_SECONDS = 0.05
CLEANUP_SECONDS = 0.5


class Cancellation(Protocol):
    def is_set(self) -> bool: ...


class HttpCarrierError(RuntimeError):
    """A carrier/cleanup fault must not trigger another HTTP attempt."""


class HttpCancelled(HttpCarrierError):
    """The caller cancelled its own transport."""


def _stop_child(process: subprocess.Popen[bytes]) -> None:
    try:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=CLEANUP_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HttpCarrierError("Owned HTTP cleanup could not be verified") from exc
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def _transport_result(stdout: bytes, max_body_bytes: int) -> bytes:
    if len(stdout) > max_body_bytes * 2 + 1024:
        raise HttpCarrierError("HTTP worker exceeded its output bound")
    try:
        packet = wire_json.loads(stdout)
        if not isinstance(packet, dict) or set(packet) != {"kind", "body"}:
            raise HttpCarrierError("Invalid transport envelope")
        kind = packet["kind"]
        if kind == "timeout":
            raise requests.Timeout("Absolute HTTP deadline exceeded")
        if kind == "request_error":
            raise requests.RequestException("Owned HTTP request failed")
        if kind == "response_error":
            raise ValueError("HTTP response exceeded its resource bound")
        if kind != "ok" or not isinstance(packet["body"], str):
            raise HttpCarrierError("HTTP worker failed before completion")
        body = base64.b64decode(packet["body"], validate=True)
        if len(body) > max_body_bytes:
            raise ValueError("HTTP response exceeded its resource bound")
        return body
    except (wire_json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HttpCarrierError(
            "HTTP worker returned invalid transport evidence"
        ) from exc


def bounded_post(
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, Any],
    timeout: float,
    deadline: float,
    max_body_bytes: int,
    cancel: Cancellation | None = None,
    require_public: bool = False,
) -> bytes:
    """One request within the caller's deadline, including headers/DNS/body reads."""
    if sys.platform != "linux":
        raise HttpCarrierError("Owned HTTP transport requires Linux/WSL")
    if cancel is not None and cancel.is_set():
        raise HttpCancelled("HTTP request cancelled before startup")
    if deadline <= time.monotonic():
        raise requests.Timeout("Absolute HTTP deadline expired before startup")
    if type(max_body_bytes) is not int or not 1 <= max_body_bytes <= MAX_BODY_BYTES:
        raise ValueError("Invalid HTTP body bound")
    payload = wire_json.dumps(
        {
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout,
            "deadline": deadline,
            "max_body_bytes": max_body_bytes,
            "parent_pid": os.getpid(),
            "require_public": require_public,
        },
        allow_nan=False,
        separators=(",", ":"),
    ).encode()
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("HTTP request exceeds transport input bound")
    environment = dict(os.environ)
    for key in ("LLM_API_KEY", "VLM_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"):
        environment.pop(key, None)
    # Explicit API headers are the authority, not an implicit user's netrc.
    environment["NETRC"] = os.devnull
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            bufsize=0,
            env=environment,
        )
    except OSError as exc:
        raise HttpCarrierError("HTTP worker could not start") from exc
    pending: bytes | None = payload
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise HttpCancelled("Owned HTTP request cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests.Timeout("Absolute HTTP deadline exceeded")
            try:
                stdout, _stderr = process.communicate(
                    pending, timeout=min(POLL_SECONDS, remaining)
                )
                break
            except subprocess.TimeoutExpired:
                pending = None  # communicate retains unsent input, never resubmit it.
        if process.returncode != 0:
            raise HttpCarrierError("HTTP worker did not complete its protocol")
        return _transport_result(stdout, max_body_bytes)
    finally:
        _stop_child(process)


def _parent_death_guard(parent_pid: int) -> None:
    """A killed CLI cannot leave an HTTP worker behind, even outside its group."""
    if sys.platform != "linux" or parent_pid <= 1 or os.getppid() != parent_pid:
        raise OSError("HTTP worker has no current owned parent")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent_pid:
        raise OSError("HTTP parent-death protection is unavailable")


def _worker_request(packet: dict[str, Any]) -> bytes:
    _parent_death_guard(packet["parent_pid"])
    maximum = packet["max_body_bytes"]
    if type(maximum) is not int or not 1 <= maximum <= MAX_BODY_BYTES:
        raise ValueError("Invalid worker response bound")
    remaining = min(packet["timeout"], packet["deadline"] - time.monotonic())
    if remaining <= 0:
        raise requests.Timeout("HTTP deadline expired before request")
    if packet.get("require_public", False):
        validate_external_endpoint(packet["url"])
        from urllib3.connectionpool import HTTPSConnectionPool

        HTTPSConnectionPool.ConnectionCls = PublicHTTPSConnection
    session = requests.Session()
    session.trust_env = False
    with (
        session,
        session.post(
            packet["url"],
            headers=packet["headers"],
            json=packet["json"],
            timeout=remaining,
            stream=True,
            allow_redirects=False,
        ) as response,
    ):
        if 300 <= response.status_code < 400:
            raise requests.RequestException("API redirects are not accepted")
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_content(chunk_size=4096):
            if len(content) + len(chunk) > maximum:
                raise ValueError("HTTP response exceeded its resource bound")
            content.extend(chunk)
        return bytes(content)


def _worker_main() -> None:
    kind, body = "worker_error", ""
    try:
        incoming = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(incoming) > MAX_INPUT_BYTES:
            raise ValueError("Worker input bound exceeded")
        packet = wire_json.loads(incoming)
        content = _worker_request(packet)
        kind, body = "ok", base64.b64encode(content).decode("ascii")
    except requests.Timeout:
        kind = "timeout"
    except requests.RequestException:
        kind = "request_error"
    except (ValueError, TypeError, KeyError):
        kind = "response_error"
    except (OSError, MemoryError):
        pass
    sys.stdout.write(
        wire_json.dumps({"kind": kind, "body": body}, separators=(",", ":"))
    )
    sys.stdout.flush()


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    _worker_main()
