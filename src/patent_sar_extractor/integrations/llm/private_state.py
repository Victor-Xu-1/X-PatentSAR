"""Bounded private control files, outside source, outputs and installed code."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from .evidence_protocol import _invalid_constant, _unique_object

MAX_CONTROL_BYTES = 32768


def private_root(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("LLM control state must not follow links")
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ValueError("LLM control state must remain outside the repository")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("LLM control state must be private and owned")
    return path


def read_private(path: Path, maximum: int = MAX_CONTROL_BYTES) -> dict[str, Any]:
    if not path.is_absolute() or any(p.is_symlink() for p in path.parents):
        raise ValueError("Unsafe LLM control path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
            or info.st_size > maximum
        ):
            raise ValueError("Unsafe or excessive LLM control file")
        content = stream.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("LLM control bound exceeded")
    result = json.loads(
        content, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
    )
    if not isinstance(result, dict):
        raise TypeError("LLM control file is not an object")
    return result


def read_budget(path: Path, job_id: str, limit: int) -> int:
    """The sole quota-record validator; missing records are never reset to zero."""
    value = read_private(path)
    if (
        set(value) != {"job_id", "limit", "calls"}
        or value["job_id"] != job_id
        or type(value["limit"]) is not int
        or value["limit"] != limit
        or type(value["calls"]) is not int
        or not 0 <= value["calls"] <= limit
    ):
        raise ValueError("Invalid persisted API call budget")
    return value["calls"]


def write_private(
    path: Path, payload: dict[str, Any], *, exclusive: bool = False
) -> None:
    root = private_root(path.parent)
    content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    if len(content) > MAX_CONTROL_BYTES:
        raise ValueError("LLM control bound exceeded")
    if path.exists() or path.is_symlink():
        if exclusive:
            raise FileExistsError("Immutable LLM context already exists")
        read_private(path)
    fd, temporary = tempfile.mkstemp(prefix=".llm-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path, follow_symlinks=False)
        else:
            os.replace(temporary, path)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
