"""One Linux owned-parent death guard for finite subprocesses, not a service."""

import ctypes
import os
import signal
import sys


def arm_parent_death(parent_pid: int) -> None:
    """Refuse a stale/missing owner; a killed owner cannot leave a live child."""
    if (
        sys.platform != "linux"
        or type(parent_pid) is not int
        or parent_pid <= 1
        or os.getppid() != parent_pid
    ):
        raise OSError("Worker has no current owned parent")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent_pid:
        raise OSError("Worker parent-death protection is unavailable")
