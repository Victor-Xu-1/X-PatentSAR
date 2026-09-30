"""Independent durable environment state; patent workspace schema stays unchanged."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .environment_models import EnvironmentOperation
from .errors import WebError
from .files import private_directory
from .storage import encode, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
 id INTEGER PRIMARY KEY CHECK(id=1), install_root TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0, checked_at TEXT
);
CREATE TABLE IF NOT EXISTS components (
 id TEXT PRIMARY KEY, source_key TEXT NOT NULL, report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
 id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL,
 action TEXT NOT NULL, component_ids TEXT NOT NULL, install_root TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
 spec TEXT NOT NULL, identity TEXT, stage TEXT NOT NULL DEFAULT '等待执行',
 completed_components TEXT NOT NULL DEFAULT '[]', log_tail TEXT NOT NULL DEFAULT '[]',
 error TEXT, applied INTEGER NOT NULL DEFAULT 0,
 cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_environment_operation
 ON operations((1)) WHERE status IN ('queued','running');
CREATE INDEX IF NOT EXISTS environment_history ON operations(created_at);
"""


class EnvironmentStore:
    def __init__(self, state_root: Path, install_root: Path) -> None:
        self.root = private_directory(state_root / "environments")
        self.path = self.root / "environment.sqlite3"
        try:
            fd = os.open(
                self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            info = self.path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                raise WebError(
                    400,
                    "unsafe_database",
                    "Environment state must be a private regular file.",
                )
        else:
            os.close(fd)
        with self.connect() as connection:
            if connection.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise WebError(
                    409,
                    "environment_schema",
                    "Environment state version is not supported.",
                )
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            connection.execute("PRAGMA user_version=1")
            connection.execute(
                "INSERT OR IGNORE INTO settings(id,install_root) VALUES(1,?)",
                (str(install_root),),
            )

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
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

    def settings(self) -> dict[str, Any]:
        with self.connect() as connection:
            return dict(
                connection.execute("SELECT * FROM settings WHERE id=1").fetchone()
            )

    def save_settings(self, root: Path, expected_revision: int) -> dict[str, Any]:
        with self.connect(write=True) as connection:
            revision = connection.execute(
                "SELECT revision FROM settings WHERE id=1"
            ).fetchone()[0]
            if revision != expected_revision:
                raise WebError(
                    409,
                    "environment_revision",
                    "Installation settings changed; refresh before saving.",
                )
            if connection.execute(
                "SELECT 1 FROM operations WHERE status IN ('queued','running')"
            ).fetchone():
                raise WebError(
                    409,
                    "environment_busy",
                    "Wait for the active environment operation before changing location.",
                )
            connection.execute(
                "UPDATE settings SET install_root=?,revision=revision+1 WHERE id=1",
                (str(root),),
            )
        return self.settings()

    def enqueue(
        self,
        request_id: str,
        fingerprint: str,
        spec: dict[str, Any],
        expected_revision: int,
    ) -> tuple[EnvironmentOperation, bool]:
        with self.connect(write=True) as connection:
            previous = connection.execute(
                "SELECT * FROM operations WHERE request_id=?", (request_id,)
            ).fetchone()
            if previous is not None:
                if previous["fingerprint"] != fingerprint:
                    raise WebError(
                        409,
                        "environment_request_conflict",
                        "The request ID already belongs to a different operation.",
                    )
                return self.operation(dict(previous)), False
            settings = connection.execute(
                "SELECT * FROM settings WHERE id=1"
            ).fetchone()
            if (
                settings["revision"] != expected_revision
                or settings["install_root"] != spec["install_root"]
            ):
                raise WebError(
                    409,
                    "environment_revision",
                    "Installation settings changed; refresh before starting.",
                )
            if connection.execute(
                "SELECT 1 FROM operations WHERE status IN ('queued','running')"
            ).fetchone():
                raise WebError(
                    409, "environment_busy", "Another environment operation is active."
                )
            if (
                connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
                >= 1000
            ):
                raise WebError(
                    413,
                    "environment_history_limit",
                    "Environment history has reached its operator retention limit.",
                )
            operation_id = uuid.uuid4().hex
            payload = {**spec, "operation_id": operation_id}
            connection.execute(
                "INSERT INTO operations(id,request_id,fingerprint,action,component_ids,install_root,status,created_at,spec) VALUES(?,?,?,?,?,?,'queued',?,?)",
                (
                    operation_id,
                    request_id,
                    fingerprint,
                    spec["action"],
                    encode(spec["component_ids"]),
                    spec["install_root"],
                    now(),
                    encode(payload),
                ),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
        return self.operation(dict(row)), True

    def row(self, operation_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
        if row is None:
            raise WebError(
                404,
                "environment_operation_missing",
                "Environment operation does not exist.",
            )
        return dict(row)

    @staticmethod
    def operation(row: dict[str, Any]) -> EnvironmentOperation:
        return EnvironmentOperation(
            **{
                key: row[key]
                for key in (
                    "id",
                    "request_id",
                    "action",
                    "status",
                    "created_at",
                    "started_at",
                    "finished_at",
                    "install_root",
                    "stage",
                )
            },
            component_ids=json.loads(row["component_ids"]),
            completed_components=json.loads(row["completed_components"]),
            log_tail=json.loads(row["log_tail"]),
            error=json.loads(row["error"]) if row["error"] else None,
            applied=bool(row["applied"]),
        )

    def history(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM operations"
        if active_only:
            query += " WHERE status IN ('queued','running')"
        query += " ORDER BY created_at DESC LIMIT 20"
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query).fetchall()]

    def request_cancel(self, operation_id: str) -> EnvironmentOperation:
        with self.connect(write=True) as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM operations WHERE id=?", (operation_id,)
                ).fetchone()
                is None
            ):
                raise WebError(
                    404,
                    "environment_operation_missing",
                    "Environment operation does not exist.",
                )
            connection.execute(
                "UPDATE operations SET cancel_requested=1 WHERE id=? AND status IN ('queued','running')",
                (operation_id,),
            )
        return self.operation(self.row(operation_id))

    def update(self, operation_id: str, **fields: Any) -> None:
        allowed = {
            "status",
            "started_at",
            "finished_at",
            "identity",
            "stage",
            "completed_components",
            "log_tail",
            "error",
            "applied",
        }
        if not fields or not set(fields) <= allowed:
            raise ValueError("Unsupported environment operation update")
        with self.connect(write=True) as connection:
            connection.execute(
                "UPDATE operations SET "
                + ",".join(key + "=?" for key in fields)
                + " WHERE id=?",
                (*fields.values(), operation_id),
            )

    def reports(self, source_key: str) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            return {
                row["id"]: json.loads(row["report"])
                for row in connection.execute(
                    "SELECT * FROM components WHERE source_key=?", (source_key,)
                )
            }

    def publish_reports(self, source_key: str, reports: list[dict[str, Any]]) -> None:
        with self.connect(write=True) as connection:
            for report in reports:
                connection.execute(
                    "INSERT INTO components(id,source_key,report) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET source_key=excluded.source_key,report=excluded.report",
                    (report["id"], source_key, encode(report)),
                )
            connection.execute("UPDATE settings SET checked_at=? WHERE id=1", (now(),))
