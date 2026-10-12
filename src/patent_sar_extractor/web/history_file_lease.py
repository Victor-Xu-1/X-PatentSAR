"""Per-inode Linux proof against open readers/writers, without /proc privileges."""

from __future__ import annotations

import errno
import fcntl
import os
import signal
from contextlib import contextmanager


def lease_intact(fd: int) -> None:
    if fcntl.fcntl(fd, fcntl.F_GETLEASE) != fcntl.F_WRLCK:
        raise OSError(errno.EBUSY, "Another reader/writer requested this file")


@contextmanager
def exclusive_file(fd: int):
    # SIGURG's default is ignored; no global handler is installed or changed.
    # Each hash chunk and the final unlink recheck the kernel lease state.
    if signal.getsignal(signal.SIGURG) not in {signal.SIG_DFL, signal.SIG_IGN}:
        raise OSError(errno.EBUSY, "Conflicting file-lease signal owner")
    fcntl.fcntl(fd, fcntl.F_SETOWN, os.getpid())
    fcntl.fcntl(fd, fcntl.F_SETSIG, signal.SIGURG)
    fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_WRLCK)
    try:
        lease_intact(fd)
        yield
        lease_intact(fd)
    finally:
        fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_UNLCK)
