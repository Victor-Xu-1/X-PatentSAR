"""Private SQLite v1 state; short transactions and per-call connections."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from patent_sar_extractor.contracts import WEB_API_SCHEMA_VERSION

from .errors import WebError
from .files import private_directory
from .history_storage import SCHEMA as HISTORY_SCHEMA
from .history_storage import ensure_project_visible, tombstone

if TYPE_CHECKING:
    from .workspace_locations import WorkspaceLocations


def now() -> str:
    return datetime.now(UTC).isoformat()


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, csrf_token TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, patent_id TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 pdf_rel TEXT, sha256 TEXT, expected_sha256 TEXT, page_count INTEGER NOT NULL DEFAULT 0,
 historical INTEGER NOT NULL DEFAULT 0, run_root TEXT, import_key TEXT UNIQUE,
 snapshot TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS compounds (
 project_id TEXT NOT NULL REFERENCES projects(id), id TEXT NOT NULL,
 ordinal INTEGER NOT NULL, payload TEXT NOT NULL, image_path TEXT, geometry_space TEXT NOT NULL,
 PRIMARY KEY(project_id, id)
);
CREATE TABLE IF NOT EXISTS reviews (
 project_id TEXT NOT NULL REFERENCES projects(id), compound_id TEXT NOT NULL,
 decision TEXT NOT NULL, note TEXT NOT NULL, revision INTEGER NOT NULL,
 updated_at TEXT NOT NULL, PRIMARY KEY(project_id,compound_id)
);
CREATE TABLE IF NOT EXISTS review_audit (
 id INTEGER PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 compound_id TEXT NOT NULL, decision TEXT NOT NULL, note TEXT NOT NULL,
 revision INTEGER NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(project_id,compound_id,revision)
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
 spec TEXT NOT NULL, identity TEXT, error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_project_job
 ON jobs(project_id) WHERE status IN ('queued','running');
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status,created_at);
CREATE INDEX IF NOT EXISTS compounds_order ON compounds(project_id,ordinal);
"""


class Store:
    @property
    def locations(self) -> WorkspaceLocations:
        from .workspace_locations import WorkspaceLocations

        return WorkspaceLocations(self.root)

    def __init__(self, state_root: str | Path) -> None:
        self.root = private_directory(Path(state_root).expanduser())
        self.path = self.root / "workspace.sqlite3"
        try:
            fd = os.open(
                self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            info = self.path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                raise WebError(
                    400,
                    "unsafe_database",
                    "Workspace database must be a private regular file.",
                )
        else:
            os.close(fd)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, WEB_API_SCHEMA_VERSION):
                raise WebError(
                    409,
                    "schema_version",
                    "Workspace schema is not supported by this server.",
                )
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            connection.executescript(HISTORY_SCHEMA)
            connection.execute(f"PRAGMA user_version={WEB_API_SCHEMA_VERSION}")

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    def project(self, project_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute("BEGIN")
            ensure_project_visible(connection, project_id)
            row = connection.execute(
                "SELECT * FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        if row is None:
            raise WebError(404, "project_not_found", "Project does not exist.")
        return dict(row)

    def job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise WebError(404, "job_not_found", "Job does not exist.")
        return dict(row)

    def compound(self, project_id: str, compound_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute("BEGIN")
            ensure_project_visible(connection, project_id)
            row = connection.execute(
                "SELECT * FROM compounds WHERE project_id=? AND id=?",
                (project_id, compound_id),
            ).fetchone()
        if row is None:
            raise WebError(
                404,
                "compound_not_found",
                "Compound is not in the activity-led result set.",
            )
        return dict(row)

    def snapshot(
        self,
        project_id: str,
        snapshot: dict[str, Any],
        compounds: list[dict[str, Any]],
        *,
        expected_run_root: str,
        expected_sha256: str | None,
    ) -> bool:
        # Serialize bounded projections before acquiring SQLite's only writer.
        # Slow CPU/IO must not strand process ownership or cancellation updates.
        values = [
            (
                project_id,
                c["dto"]["id"],
                i,
                encode(c["dto"]),
                c["image_path"],
                c["geometry_space"],
            )
            for i, c in enumerate(compounds)
        ]
        encoded_snapshot = encode(snapshot)
        with self.connect(write=True) as connection:
            current = connection.execute(
                "SELECT run_root,sha256 FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if (
                current is None
                or tombstone(connection, "project", project_id)["deleted_at"]
                is not None
                or current["run_root"] != expected_run_root
                or current["sha256"] != expected_sha256
            ):
                return False  # Source ownership changed; discard before any writes.
            connection.execute(
                "DELETE FROM compounds WHERE project_id=?", (project_id,)
            )
            connection.executemany(
                "INSERT INTO compounds(project_id,id,ordinal,payload,image_path,geometry_space) VALUES(?,?,?,?,?,?)",
                values,
            )
            connection.execute(
                "UPDATE projects SET snapshot=?,historical=?,updated_at=? WHERE id=?",
                (encoded_snapshot, int(snapshot["is_historical"]), now(), project_id),
            )
        return True
