"""The existing cross-process analysis lease, shared by inference and trash writes."""

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import WebError
from .files import directory_descriptor, private_directory


def _acquire(state_root: Path, *, create: bool) -> int | None:
    root = state_root / "analysis"
    descriptor = None
    try:
        if create:
            private_directory(root)
        try:
            parent = directory_descriptor(root)
        except FileNotFoundError:
            if create:
                raise
            return None
        try:
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
            if create:
                flags |= os.O_CREAT
            try:
                descriptor = os.open("operation.lock", flags, 0o600, dir_fd=parent)
            except FileNotFoundError:
                if create:
                    raise
                return None
        finally:
            os.close(parent)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise WebError(
                503, "analysis_lock", "Analysis operation lock is not private."
            )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WebError(
                503, "analysis_busy", "Another owned analysis operation is running."
            ) from error
        return descriptor
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise WebError(
            503, "analysis_lock", "Analysis lease could not be checked safely."
        ) from error
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise


def _release(descriptor: int | None) -> None:
    if descriptor is not None:
        os.close(descriptor)


@contextmanager
def analysis_lease(state_root: Path, *, create: bool = True) -> Iterator[None]:
    descriptor = _acquire(state_root, create=create)
    try:
        yield
    finally:
        _release(descriptor)


def analysis_block(state_root: Path) -> str | None:
    try:
        with analysis_lease(state_root, create=False):
            return None
    except WebError as error:
        return (
            "A molecular analysis is active; wait for verified cleanup before removing this project."
            if error.code == "analysis_busy"
            else "The analysis lease cannot be verified safely."
        )
