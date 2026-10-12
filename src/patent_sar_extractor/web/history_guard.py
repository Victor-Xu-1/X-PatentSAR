"""One short nonblocking guard for all history visibility mutations."""

import fcntl
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from .errors import WebError


@contextmanager
def history_guard(root: Path, *, create=True):
    try:
        descriptor = os.open(
            root / "history-write.lock",
            (os.O_CREAT if create else 0) | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as error:
        raise WebError(
            409, "history_lock", "History control ownership cannot be verified."
        ) from error
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise WebError(
                409, "history_lock", "History control ownership cannot be verified."
            )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WebError(
                409,
                "history_busy",
                "Another history action is active. Refresh before trying again.",
            ) from error
        yield
    finally:
        os.close(descriptor)
