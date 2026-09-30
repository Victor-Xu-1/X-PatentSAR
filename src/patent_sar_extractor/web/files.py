"""Bounded, no-symlink openat reads beneath operator-approved roots."""

from __future__ import annotations

import json
import os
import stat
import sysconfig
from pathlib import Path
from typing import Any, BinaryIO

from .errors import WebError

MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 25000


def private_directory(path: Path) -> Path:
    if path.is_symlink():
        raise WebError(400, "unsafe_state", "State directory must not be a symlink.")
    resolved = path.resolve()
    protected = {Path(__file__).resolve().parents[1]}
    protected.update(
        Path(value).resolve()
        for key, value in sysconfig.get_paths().items()
        if key in {"purelib", "platlib"}
    )
    if any(resolved.is_relative_to(root) for root in protected) or any(
        (parent / ".git").exists() for parent in (resolved, *resolved.parents)
    ):
        raise WebError(
            400,
            "state_in_source",
            "Runtime state must not reside in a Git checkout or installed package.",
        )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = resolved.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise WebError(
            400, "unsafe_state", "State directory must be private and operator-owned."
        )
    return resolved


class SafeFiles:
    def __init__(self, root: Path) -> None:
        if root.is_symlink() or not root.is_dir():
            raise WebError(
                400,
                "unsafe_directory",
                "Run directory must be an existing real directory.",
            )
        self.root = root.resolve()

    def relative(self, value: str | Path) -> Path:
        raw = str(value)
        if not raw or "\x00" in raw or "\\" in raw:
            raise WebError(400, "unsafe_asset", "Asset path is not allowed.")
        path = Path(raw)
        if path.is_absolute():
            try:
                path = path.relative_to(self.root)
            except ValueError as exc:
                raise WebError(
                    400, "unsafe_asset", "Asset lies outside its approved run."
                ) from exc
        if not path.parts or any(p in {".", ".."} or ":" in p for p in path.parts):
            raise WebError(400, "unsafe_asset", "Asset path is not allowed.")
        return path

    def open(self, value: str | Path, *, max_bytes: int) -> BinaryIO:
        relative = self.relative(value)
        parent_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in relative.parts[:-1]:
                next_fd = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
                )
                os.close(parent_fd)
                parent_fd = next_fd
            fd = os.open(
                relative.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise WebError(
                404, "asset_unavailable", "Asset is missing or unsafe."
            ) from exc
        finally:
            os.close(parent_fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            os.close(fd)
            raise WebError(413, "asset_limit", "Asset is not a regular bounded file.")
        return os.fdopen(fd, "rb")

    def read(self, value: str | Path, *, max_bytes: int) -> bytes:
        with self.open(value, max_bytes=max_bytes) as stream:
            content = stream.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise WebError(413, "asset_limit", "Asset exceeds its size limit.")
        return content

    def json(self, value: str | Path, *, optional: bool = True) -> Any:
        try:
            content = self.read(value, max_bytes=MAX_ARTIFACT_BYTES)
        except WebError as exc:
            if optional and exc.code == "asset_unavailable":
                return None
            raise
        try:
            return json.loads(content, parse_constant=_invalid_constant)
        except (ValueError, RecursionError, UnicodeError) as exc:
            raise WebError(
                422, "invalid_artifact", "Run artifact contains invalid JSON."
            ) from exc


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def records(payload: object, key: str) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if not isinstance(payload, dict) or not isinstance(payload.get(key, []), list):
        raise WebError(
            422, "invalid_artifact", "Run artifact has an invalid record collection."
        )
    items = payload.get(key, [])
    if len(items) > MAX_RECORDS or any(not isinstance(x, dict) for x in items):
        raise WebError(
            422,
            "artifact_limit",
            "Run artifact exceeds record limits or has invalid records.",
        )
    return items
