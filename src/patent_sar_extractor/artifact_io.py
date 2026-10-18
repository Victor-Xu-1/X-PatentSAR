"""Small, dependency-free helpers for durable JSON artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .artifact_catalog import pack_shared_json, read_artifact_json
from .artifact_nodes import MAX_ARTIFACT_BYTES


def _shared_parts(encoded):
    encoder = json.JSONEncoder(
        ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    written = 0
    for part in encoder.iterencode(encoded):
        written += len(part.encode("utf-8"))
        if written > MAX_ARTIFACT_BYTES:
            raise ValueError("Shared JSON artifact exceeds its byte bound")
        yield part


def artifact_json_bytes(payload: Any, *, shared: bool = False) -> bytes:
    """Canonical checkpoint bytes; shared output uses the atomic writer's codec."""
    if shared:
        return "".join(_shared_parts(pack_shared_json(payload))).encode("utf-8")
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2).encode()


def write_json_atomic(path: str | Path, payload: Any, *, shared: bool = False) -> None:
    """Write JSON atomically so interrupted stages never expose partial data."""

    if shared:
        payload = pack_shared_json(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            if shared:
                for part in _shared_parts(payload):
                    handle.write(part)
            else:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_json(path: str | Path, default: Any) -> Any:
    """Load a JSON artifact, returning ``default`` only when it is absent."""

    target = Path(path)
    if not target.is_file():
        return default
    with target.open("r", encoding="utf-8") as handle:
        return read_artifact_json(handle)
