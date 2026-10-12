"""Hash only proved first-party assets; retain shared, imported, linked or open data."""

from __future__ import annotations

import os
import re
import stat
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from .environment_records import environment_spec
from .errors import WebError
from .files import directory_descriptor
from .history_asset_models import (
    MAX_CLEANUP_BYTES,
    MAX_CLEANUP_FILES,
    UPLOAD_FILE,
    CleanupDirectory,
    CleanupManifest,
)
from .history_asset_references import asset_references, record
from .history_file_fingerprint import fingerprint_file

UUID = re.compile(r"[a-f0-9]{32}")


@dataclass(frozen=True)
class AssetTarget:
    path: Path
    anchor: Path
    directory: bool = False
    expected_sha256: str | None = None


def targets(history, snapshot, connection):
    selected = frozenset((kind, identifier) for kind, identifier, _ in snapshot.entries)
    refs = asset_references(history.store, connection, selected)
    result, retained = set(), 0
    store = history.store
    exports = (
        {row["id"]: row for row in history.exports.records()}
        if any(kind == "export" for kind, _, _ in snapshot.entries)
        else {}
    )
    with ExitStack() as stack:
        environment = (
            stack.enter_context(history.environments.connect())
            if any(kind == "environment_operation" for kind, _, _ in snapshot.entries)
            else None
        )
        rows = [
            (
                kind,
                exports[identifier]
                if kind == "export"
                else history._row(
                    environment if kind == "environment_operation" else connection,
                    kind,
                    identifier,
                ),
            )
            for kind, identifier, _ in snapshot.entries
        ]
    for kind, row in rows:
        if kind == "export":
            if row["status"] == "available":
                path = Path(row["path"])
                result.add(AssetTarget(path, store.locations.result_anchor(path)))
            elif row["status"] != "missing":
                retained += 1
        elif kind == "project":
            if row["id"] in refs.projects:
                retained += 1
                continue
            if row["pdf_rel"]:
                path = store.locations.pdf_path(row)
                anchor = next(
                    (
                        root
                        for root in store.locations.roots("uploads")
                        if path.parent == root
                    ),
                    None,
                )
                if (
                    anchor is not None
                    and UPLOAD_FILE.fullmatch(path.name)
                    and isinstance(row["sha256"], str)
                    and re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
                ):
                    store.locations.policy.validate("uploads", str(anchor))
                    result.add(AssetTarget(path, anchor, expected_sha256=row["sha256"]))
                else:
                    retained += 1
            if row["run_root"] and row["import_key"]:
                retained += 1  # imported directories are never adopted for deletion
        elif kind == "job":
            if row["project_id"] in refs.projects:
                retained += 1
                continue
            spec = record(row["spec"])
            if not spec.get("output_dir"):
                continue
            path = Path(spec["output_dir"])
            anchor = store.locations.result_anchor(path)
            if (
                path == anchor / row["project_id"] / row["id"]
                and UUID.fullmatch(row["id"])
                and UUID.fullmatch(row["project_id"])
                and spec.get("job_id") == row["id"]
                and spec.get("project_id") == row["project_id"]
            ):
                result.add(AssetTarget(path, anchor, True))
            else:
                retained += 1
        elif kind == "environment_operation":
            spec, _ = environment_spec(row, store.root)
            result.add(
                AssetTarget(
                    Path(spec.output_dir), store.root / "environments/operations", True
                )
            )
    return result, refs, retained


def inventory(history, snapshot, connection) -> CleanupManifest:
    candidates, refs, retained = targets(history, snapshot, connection)
    files, directories, total_bytes = {}, {}, 0
    started = time.monotonic()
    for target in sorted(candidates, key=lambda value: str(value.path)):
        if refs.protects(target.path, target.expected_sha256):
            retained += 1
            continue
        try:
            local_files, local_directories = _scan(target, started)
        except (OSError, ValueError):
            retained += 1
            continue
        if any(refs.protects(Path(item.path), item.sha256) for item in local_files):
            retained += 1
            continue
        if target.expected_sha256 is not None and any(
            item.sha256 != target.expected_sha256 for item in local_files
        ):
            retained += 1
            continue
        for item in local_files:
            if item.path not in files:
                files[item.path] = item
                total_bytes += item.identity[2]
        directories.update((item.path, item) for item in local_directories)
        if (
            len(files) > MAX_CLEANUP_FILES
            or len(directories) > MAX_CLEANUP_FILES
            or total_bytes > MAX_CLEANUP_BYTES
        ):
            raise WebError(
                413,
                "history_asset_limit",
                "The complete file inventory exceeds its safe resource bound; nothing was omitted or deleted.",
            )
    return CleanupManifest(
        files=[files[key] for key in sorted(files)],
        directories=[directories[key] for key in sorted(directories)],
        retained_targets=retained,
        references_sha256=refs.sha256,
    )


def _scan(target: AssetTarget, started: float):
    collected, directories, pending, size = [], [], [target.path], 0
    if not os.path.lexists(target.path):
        return collected, directories
    anchor_fd = directory_descriptor(target.anchor)
    try:
        device = os.fstat(anchor_fd).st_dev
    finally:
        os.close(anchor_fd)
    while pending:
        if (
            time.monotonic() - started > 30
            or len(pending) + len(collected) + len(directories) > MAX_CLEANUP_FILES
        ):
            raise WebError(
                413,
                "history_asset_limit",
                "The complete file inventory reached its time/entry bound; nothing was deleted.",
            )
        path = pending.pop()
        parent = directory_descriptor(path.parent)
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if (
                info.st_uid != os.getuid()
                or info.st_dev != device
                or path == target.anchor
                or not path.is_relative_to(target.anchor)
            ):
                raise ValueError("foreign asset")
            if stat.S_ISDIR(info.st_mode):
                if not target.directory:
                    raise ValueError("not a file")
                fd = os.open(
                    path.name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent,
                )
                try:
                    directories.append(
                        CleanupDirectory(
                            path=str(path),
                            anchor=str(target.anchor),
                            identity=(info.st_dev, info.st_ino),
                        )
                    )
                    with os.scandir(fd) as children:
                        for child in children:
                            if (
                                len(pending) + len(collected) + len(directories)
                                >= MAX_CLEANUP_FILES
                            ):
                                raise WebError(
                                    413,
                                    "history_asset_limit",
                                    "The complete directory inventory exceeds its entry bound; nothing was deleted.",
                                )
                            if child.name in {".git", ".ssh"} or child.name.startswith(
                                ".patentsar-clear-"
                            ):
                                raise ValueError("protected directory")
                            pending.append(path / child.name)
                finally:
                    os.close(fd)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                size += info.st_size
                if size > MAX_CLEANUP_BYTES:
                    raise WebError(
                        413,
                        "history_asset_limit",
                        "The complete hashing inventory exceeds its byte bound; nothing was deleted.",
                    )
                collected.append(
                    fingerprint_file(parent, path, target.anchor, info, started)
                )
            else:
                raise ValueError("linked, open or special asset")
        finally:
            os.close(parent)
    return collected, directories
