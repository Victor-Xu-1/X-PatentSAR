"""Small, dependency-free helpers for durable JSON artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(path: str | Path, payload: Any) -> None:
    """Write JSON atomically so interrupted stages never expose partial data."""

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
        return json.load(handle)
