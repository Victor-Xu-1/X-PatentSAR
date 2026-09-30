"""Stdlib-only offline worker protocol, usable in both isolated interpreters."""

from __future__ import annotations

import json
import os
import resource
import socket
import sys
from typing import Any, TextIO

ADMET_VERSION = "2.0.1"
ADMET_BUNDLE_SHA256 = "4436035bee9294e23ac71d7df329e6d87225d7dbd8d0e7db559f00d8feb117bc"
ADMET_WHEEL_SHA256 = "fef3527f637abb00d272cf824e8eef0136fe31ebde6c56881f1a8c02c0417806"
MAX_INPUT = 128 * 1024


def _network_denied(*args: object, **kwargs: object) -> None:
    raise OSError("Analysis workers are offline; provision models before use")


def prepare() -> TextIO:
    """Keep even native model logs out of the JSON channel; prohibit downloads."""
    output = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (5 * 1024**3, 5 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
    socket.socket.connect = _network_denied  # type: ignore[assignment]
    socket.socket.connect_ex = _network_denied  # type: ignore[assignment]
    socket.create_connection = _network_denied  # type: ignore[assignment]
    return output


def read_request() -> dict[str, Any]:
    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        raise ValueError("Worker input exceeds its limit")
    value = json.loads(data, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Worker input must be an object")
    return value


def reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON value")


def emit(output: TextIO, payload: object) -> None:
    output.write(
        json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        + "\n"
    )
    output.flush()
