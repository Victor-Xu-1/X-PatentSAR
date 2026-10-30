"""Exclusive durable publication: readers see no file or complete private bytes."""

from __future__ import annotations

import os
import secrets
import stat
from collections.abc import Callable
from pathlib import Path

from patent_sar_extractor.artifact_nodes import MAX_ARTIFACT_BYTES

from .files import directory_descriptor


def _owns_temporary(directory: int, name: str, identity: os.stat_result) -> bool:
    try:
        actual = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return stat.S_ISREG(actual.st_mode) and (
        actual.st_dev,
        actual.st_ino,
        actual.st_uid,
    ) == (identity.st_dev, identity.st_ino, identity.st_uid)


def publish_bytes_once(
    destination: Path,
    content: bytes,
    *,
    before_publish: Callable[[], None] | None = None,
) -> None:
    """Publish an owned temporary inode, never link an original/source inode.

    Callers own the approved private root and their narrower file/total budgets.
    Existing final files are never replaced. Failure/cancellation before commit
    exposes no prefix; cleanup unlinks only the verified temporary inode.
    """
    if (
        not destination.is_absolute()
        or not destination.name
        or any(part in {".", ".."} for part in destination.parts)
        or type(content) is not bytes
        or len(content) > MAX_ARTIFACT_BYTES
    ):
        raise ValueError("Invalid bounded write-once publication")
    directory = directory_descriptor(destination.parent)
    temporary = f".patentsar-publish-{secrets.token_hex(16)}.tmp"
    descriptor = None
    identity = None
    try:
        parent = os.fstat(directory)
        if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
            raise OSError("Write-once publication requires a private owned parent")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        identity = os.fstat(descriptor)
        stream = os.fdopen(descriptor, "wb")
        descriptor = None  # The stream now owns this exact new descriptor.
        with stream:
            if stream.write(content) != len(content):
                raise OSError("Write-once artifact was not written completely")
            stream.flush()
            os.fsync(stream.fileno())
            if before_publish is not None:
                before_publish()
            if not _owns_temporary(directory, temporary, identity):
                raise OSError("Write-once temporary identity changed")
            # Atomic no-replace name creation, from ONLY our complete temporary.
            # The final file is independent of every source/checkpoint inode.
            os.link(
                temporary,
                destination.name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        if _owns_temporary(directory, temporary, identity):
            os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            if descriptor is not None:
                os.close(descriptor)
            if identity is not None and _owns_temporary(directory, temporary, identity):
                os.unlink(temporary, dir_fd=directory)
        finally:
            os.close(directory)
