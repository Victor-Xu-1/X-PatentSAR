"""Private additive visibility markers; never delete source or audit records."""

from __future__ import annotations

import sqlite3
from typing import Any

from .errors import WebError

TOMBSTONE_SCHEMA = """
CREATE TABLE IF NOT EXISTS history_tombstones (
 kind TEXT NOT NULL CHECK(kind IN ('project','job','export','environment_operation')),
 id TEXT NOT NULL, deleted_at TEXT, generation INTEGER NOT NULL DEFAULT 0,
 previous_revision TEXT, applied_revision TEXT, action TEXT,
 PRIMARY KEY(kind,id)
);
"""
EXPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS history_exports (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS history_exports_project ON history_exports(project_id);
"""
SCHEMA = TOMBSTONE_SCHEMA + EXPORT_SCHEMA
ENVIRONMENT_SCHEMA = TOMBSTONE_SCHEMA
TERMINAL = frozenset({"complete", "failed", "cancelled", "interrupted"})


def tombstone(
    connection: sqlite3.Connection, kind: str, identifier: str
) -> dict[str, Any]:
    if (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='history_tombstones'"
        ).fetchone()
        is None
    ):
        return {"deleted_at": None, "generation": 0}
    row = connection.execute(
        "SELECT * FROM history_tombstones WHERE kind=? AND id=?", (kind, identifier)
    ).fetchone()
    return dict(row) if row else {"deleted_at": None, "generation": 0}


def ensure_project_visible(connection: sqlite3.Connection, project_id: str) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM projects p WHERE p.id=? AND NOT EXISTS "
            "(SELECT 1 FROM history_tombstones t WHERE t.kind='project' AND t.id=p.id AND t.deleted_at IS NOT NULL)",
            (project_id,),
        ).fetchone()
        is None
    ):
        raise WebError(
            404, "project_not_found", "Project does not exist in the active workspace."
        )


def ensure_job_visible(connection: sqlite3.Connection, job_id: str) -> None:
    row = connection.execute(
        "SELECT project_id FROM jobs WHERE id=?", (job_id,)
    ).fetchone()
    if row is None or tombstone(connection, "job", job_id)["deleted_at"] is not None:
        raise WebError(
            404, "job_not_found", "Task does not exist in the active workspace."
        )
    ensure_project_visible(connection, row["project_id"])


def lifecycle_block(row: dict[str, Any]) -> str | None:
    if row["status"] not in TERMINAL:
        return "Only terminal records can be moved to the trash. Finish or cancel the active operation first."
    if row["identity"] is not None:
        return "Retained process ownership must be safely reconciled before this record can be removed."
    return None


def project_block(connection: sqlite3.Connection, project_id: str) -> str | None:
    if connection.execute(
        "SELECT 1 FROM jobs WHERE project_id=? AND (status NOT IN ('complete','failed','cancelled','interrupted') OR identity IS NOT NULL) LIMIT 1",
        (project_id,),
    ).fetchone():
        return "An associated task is active or retains process ownership; reconcile it before removing this project."
    return None


def write_tombstone(
    connection: sqlite3.Connection,
    kind: str,
    identifier: str,
    deleted_at: str | None,
    expected_revision: str,
    action: str,
) -> None:
    connection.execute(
        "INSERT INTO history_tombstones(kind,id,deleted_at,generation,previous_revision,action) VALUES(?,?,?,1,?,?) "
        "ON CONFLICT(kind,id) DO UPDATE SET deleted_at=excluded.deleted_at,generation=generation+1,"
        "previous_revision=excluded.previous_revision,applied_revision=NULL,action=excluded.action",
        (kind, identifier, deleted_at, expected_revision, action),
    )


def seal_revision(
    connection: sqlite3.Connection, kind: str, identifier: str, revision: str
) -> None:
    connection.execute(
        "UPDATE history_tombstones SET applied_revision=? WHERE kind=? AND id=?",
        (revision, kind, identifier),
    )
