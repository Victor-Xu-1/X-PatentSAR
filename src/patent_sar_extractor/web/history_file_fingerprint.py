"""One streaming hash and stable identity under a native exclusive file lease."""

from __future__ import annotations

import hashlib
import os
import time

from .errors import WebError
from .history_asset_models import CleanupFile
from .history_file_lease import exclusive_file, lease_intact


def file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
    )


def hash_content(fd: int, *, deadline: float | None = None) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while block := os.read(fd, 1024 * 1024):
        lease_intact(fd)
        digest.update(block)
        if deadline is not None and time.monotonic() > deadline:
            raise WebError(
                413,
                "history_asset_limit",
                "The complete hashing inventory reached its time bound; no file was deleted.",
            )
    lease_intact(fd)
    return digest.hexdigest()


def fingerprint_file(parent: int, path, anchor, info, started: float) -> CleanupFile:
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        with exclusive_file(fd):
            if file_identity(os.fstat(fd)) != file_identity(info):
                raise ValueError("changed asset")
            digest = hash_content(fd, deadline=started + 30)
            if file_identity(os.fstat(fd)) != file_identity(info):
                raise ValueError("changed asset")
            return CleanupFile(
                path=str(path),
                anchor=str(anchor),
                identity=file_identity(info),
                sha256=digest,
            )
    finally:
        os.close(fd)
