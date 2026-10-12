"""Exact-inode, no-replace quarantine/unlink; never delete a broad directory."""

from __future__ import annotations

import ctypes
import errno
import os
import re
import stat
from pathlib import Path

from .files import directory_descriptor
from .history_asset_models import UPLOAD_FILE
from .history_file_fingerprint import file_identity, hash_content
from .history_file_lease import exclusive_file, lease_intact


def rename_exclusive(parent: int, source: str, destination: str) -> None:
    # Linux-native app boundary. RENAME_NOREPLACE prevents overwriting a foreign
    # quarantine/original even if it appears between inspection and rename.
    library = ctypes.CDLL(None, use_errno=True)
    if not hasattr(library, "renameat2"):
        raise OSError(errno.ENOTSUP, "Exclusive quarantine rename is unavailable")
    function = library.renameat2
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    if function(parent, os.fsencode(source), parent, os.fsencode(destination), 1):
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def approved_path(store, path: str, anchor: str) -> Path:
    target, root = Path(path), Path(anchor)
    if (
        not target.is_absolute()
        or str(target) != path
        or str(root) != anchor
        or target == root
        or not target.is_relative_to(root)
        or any(part in {".", "..", ".git", ".ssh"} for part in path.split("/"))
        or "\\" in path
        or any(ord(char) < 32 for char in path)
    ):
        raise ValueError("unsafe cleanup path")
    if root == store.root / "environments/operations":
        parts = target.relative_to(root).parts
        if len(parts) < 2 or re.fullmatch(r"[a-f0-9]{32}", parts[0]) is None:
            raise ValueError("not an operation asset")
    else:
        kinds = [
            kind
            for kind in ("uploads", "results")
            if root in store.locations.roots(kind)
        ]
        if len(kinds) != 1:
            raise ValueError("unregistered cleanup anchor")
        store.locations.policy.validate(kinds[0], str(root))
        parts = target.relative_to(root).parts
        if kinds[0] == "uploads":
            if len(parts) != 1 or UPLOAD_FILE.fullmatch(parts[0]) is None:
                raise ValueError("not an uploaded original")
        elif (
            len(parts) < 3
            or re.fullmatch(r"[a-f0-9]{32}", parts[0]) is None
            or (
                parts[1] != "exports"
                and re.fullmatch(r"[a-f0-9]{32}", parts[1]) is None
            )
        ):
            raise ValueError("not a recorded job/export asset")
    return target


def _inspect(parent: int, name: str):
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _verify(fd: int, item, *, renamed=False, deadline=None):
    info = os.fstat(fd)
    actual, expected = file_identity(info), item.identity
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or (actual[:4] + actual[5:] if renamed else actual)
        != (expected[:4] + expected[5:] if renamed else expected)
    ):
        raise ValueError("changed cleanup inode")
    if (
        hash_content(fd, deadline=deadline) != item.sha256
        or file_identity(os.fstat(fd)) != actual
    ):
        raise ValueError("changed cleanup content")


def remove_file(
    store, item, request_id: str, index: int, references, *, deadline=None
) -> bool:
    path = approved_path(store, item.path, item.anchor)
    stage = f".patentsar-clear-{request_id}-{index:06x}"
    parent = directory_descriptor(path.parent)
    try:
        if os.fstat(parent).st_uid != os.getuid():
            raise ValueError("foreign cleanup parent")
        original, staged = _inspect(parent, path.name), _inspect(parent, stage)
        if original is not None and staged is not None:
            raise ValueError("conflicting cleanup names")
        if original is None and staged is None:
            return True  # a committed intent may have unlinked before a crash
        fd = os.open(
            stage if staged is not None else path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent,
        )
        try:
            with exclusive_file(fd):
                _verify(fd, item, renamed=staged is not None, deadline=deadline)
                if references.protects(path, item.sha256):
                    if staged is not None:
                        rename_exclusive(parent, stage, path.name)
                        os.fsync(parent)
                    return False
                if staged is None:
                    rename_exclusive(parent, path.name, stage)
                    os.fsync(parent)
                # The same exclusive leased descriptor spans hash/rename/unlink.
                # Renaming does not change its bytes; no duplicate full hash IO.
                # No replacement/hardlink or requested lease break can pass.
                current = _inspect(parent, stage)
                if (
                    current is None
                    or file_identity(current)[:4] + file_identity(current)[5:]
                    != item.identity[:4] + item.identity[5:]
                    or current.st_nlink != 1
                ):
                    raise ValueError("changed quarantine")
                lease_intact(fd)
                os.unlink(stage, dir_fd=parent)
                os.fsync(parent)
                return True
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def remove_empty_directory(store, item, references) -> None:
    path = Path(item.path)
    if path == Path(item.anchor) or references.protects(path):
        return
    # Directory admission uses the same file boundary by validating a child.
    approved_path(store, str(path / "owned-child"), item.anchor)
    try:
        parent = directory_descriptor(path.parent)
    except FileNotFoundError:
        return
    try:
        info = _inspect(parent, path.name)
        if info is None:
            return
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or (info.st_dev, info.st_ino) != item.identity
        ):
            raise ValueError("changed cleanup directory")
        try:
            os.rmdir(path.name, dir_fd=parent)
            os.fsync(parent)
        except OSError as error:
            if error.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                raise
    finally:
        os.close(parent)
