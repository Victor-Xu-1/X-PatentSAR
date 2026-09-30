"""One live queue/recovery owner per private workspace."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

from .errors import WebError


class WorkspaceOwner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.fd: int | None = None

    def acquire(self) -> None:
        fd = os.open(
            self.root / "server.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise WebError(
                409,
                "workspace_busy",
                "Another server owns this workspace; no recovery was attempted.",
            ) from exc
        self.fd = fd

    def release(self) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
