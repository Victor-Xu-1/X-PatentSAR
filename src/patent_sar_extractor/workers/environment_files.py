"""Bounded private operation files and immutable-prefix guards; no config writes."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any


def checked_directory(value: str | Path, *, private: bool = False) -> Path:
    raw = str(value)
    path = Path(raw)
    if (
        not path.is_absolute()
        or "\\" in raw
        or "\x00" in raw
        or ":" in raw
        or any(part in {".", ".."} for part in raw.split("/"))
        or any(ord(c) < 32 for c in raw)
        or path == Path("/")
        or path.is_relative_to("/mnt")
    ):
        raise ValueError("Only approved absolute local Linux paths are supported")
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Directory links are not allowed")
    if not path.is_dir() or path.stat().st_uid != os.getuid():
        raise ValueError("Directory must exist and be operator-owned")
    if private and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("Operation directory must be private")
    if any((p / ".git").exists() for p in (path, *path.parents)):
        raise ValueError("Runtime files must remain outside source")
    return path.resolve()


def read_regular(path: Path, limit: int) -> bytes:
    if any(p.is_symlink() for p in path.parents):
        raise ValueError("Linked file parent is unsafe")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("File is not regular or exceeds its limit")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("File exceeds its limit")
        return data


def load_json(path: Path, limit: int = 64 * 1024) -> dict[str, Any]:
    value = json.loads(read_regular(path, limit), parse_constant=_invalid_number)
    if not isinstance(value, dict):
        raise TypeError("Expected a JSON object")
    return value


def _invalid_number(value: str) -> None:
    raise ValueError("Nonfinite JSON is not allowed")


def atomic_json(directory: Path, name: str, payload: object, *, limit: int) -> None:
    if name not in {
        "environment-progress.json",
        "environment-result.json",
        "environment-failure.json",
        "receipt.json",
    }:
        raise ValueError("Unknown worker artifact")
    data = json.dumps(
        payload, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode()
    if len(data) > limit:
        raise ValueError("Worker artifact exceeds its limit")
    destination = directory / name
    if destination.is_symlink():
        raise ValueError("Worker artifact must not be a link")
    temporary = directory / (name + ".writing")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def file_sha256(path: Path, *, limit: int = 512 * 1024 * 1024) -> str:
    if any(p.is_symlink() for p in path.parents):
        raise ValueError("Linked asset parent is unsafe")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Model must be a bounded regular file")
        result = hashlib.sha256()
        while data := stream.read(1024 * 1024):
            result.update(data)
    return result.hexdigest()


def verify_decimer_models(root: Path, recipe: dict[str, Any]) -> dict[str, Any]:
    checked_directory(root)
    for group in recipe["ocsrc"]:
        for item in group["files"]:
            path = root / "DECIMER-V2" / item["path"]
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError("Linked model asset")
            if (
                path.stat().st_size != item["size"]
                or file_sha256(path) != item["sha256"]
            ):
                raise ValueError("DECIMER content fingerprint differs")
        marker = root / "DECIMER-V2" / group["directory"] / ".model_url"
        if read_regular(marker, 4096).decode().strip() != group["url"]:
            raise ValueError(
                "DECIMER source marker differs; inspection must not download"
            )
    return {"ocsrc_models": 2, "files": sum(len(g["files"]) for g in recipe["ocsrc"])}
