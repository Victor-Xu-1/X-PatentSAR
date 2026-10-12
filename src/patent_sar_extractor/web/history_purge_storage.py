"""Permanent UI tombstones and exact-request receipts in one workspace writer."""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

from .errors import WebError
from .files import directory_descriptor

PURGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS history_purged_entries (
 kind TEXT NOT NULL CHECK(kind IN ('project','job','export','environment_operation')),
 id TEXT NOT NULL, purged_at TEXT NOT NULL, request_id TEXT NOT NULL,
 PRIMARY KEY(kind,id)
);
CREATE TABLE IF NOT EXISTS history_purge_requests (
 request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history_file_cleanup (
 request_id TEXT PRIMARY KEY REFERENCES history_purge_requests(request_id),
 manifest TEXT NOT NULL, sha256 TEXT NOT NULL, next_index INTEGER NOT NULL DEFAULT 0
);
"""


def attach_control(
    connection: sqlite3.Connection, root: Path, *, required=False
) -> None:
    control = root / "workspace.sqlite3"
    if not os.path.lexists(control):
        if required:
            raise WebError(
                409,
                "history_control",
                "History control is missing; no operation was changed.",
            )
        return
    descriptor = directory_descriptor(control.parent)
    try:
        info = os.stat(control.name, dir_fd=descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise WebError(
                409,
                "history_control",
                "History control must remain private and operator-owned.",
            )
        connection.execute(
            "ATTACH DATABASE ? AS history_control", (control.as_uri() + "?mode=ro",)
        )
    except OSError as error:
        raise WebError(
            409, "history_control", "History control could not be safely inspected."
        ) from error
    finally:
        os.close(descriptor)


def purge_table(connection: sqlite3.Connection) -> str | None:
    for schema in ("main", "history_control"):
        if schema == "history_control" and not any(
            row[1] == schema for row in connection.execute("PRAGMA database_list")
        ):
            continue
        if connection.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name='history_purged_entries'"
        ).fetchone():
            return schema + ".history_purged_entries"
    return None


def permanently_removed(
    connection: sqlite3.Connection,
    kind: str,
    identifier: str,
    project_id: str | None = None,
) -> bool:
    table = purge_table(connection)
    return bool(
        table
        and connection.execute(
            f"SELECT 1 FROM {table} WHERE (kind=? AND id=?) OR (kind='project' AND id=?) LIMIT 1",
            (kind, identifier, project_id),
        ).fetchone()
    )
