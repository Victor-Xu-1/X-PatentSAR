"""One private versioned SAR database, independent of extraction acceptance."""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from ...contracts import SAR_DATABASE_VERSION
from ..errors import WebError
from ..files import private_directory

SCHEMA_VERSION = SAR_DATABASE_VERSION
SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
 id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, request_sha256 TEXT NOT NULL,
 metadata TEXT NOT NULL, source_revision TEXT, deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS molecules (
 dataset_id TEXT NOT NULL REFERENCES datasets(id), id TEXT NOT NULL,
 ordinal INTEGER NOT NULL, label TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(dataset_id,id)
);
CREATE INDEX IF NOT EXISTS molecule_page ON molecules(dataset_id,ordinal);
CREATE TABLE IF NOT EXISTS regions (
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
 payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
 request_id TEXT UNIQUE NOT NULL, request_sha256 TEXT NOT NULL, status TEXT NOT NULL,
 spec TEXT NOT NULL, payload TEXT NOT NULL, root TEXT NOT NULL,
 cancel_requested INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0,
 ready INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS sar_active_dataset ON jobs(dataset_id)
 WHERE status IN ('queued','running');
CREATE UNIQUE INDEX IF NOT EXISTS sar_one_running ON jobs((1)) WHERE status='running';
CREATE TABLE IF NOT EXISTS pairs (
 job_id TEXT NOT NULL REFERENCES jobs(id), ordinal INTEGER NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(job_id,ordinal)
);
CREATE TABLE IF NOT EXISTS uploads (
 token TEXT PRIMARY KEY, filename TEXT NOT NULL, root TEXT NOT NULL,
 sha256 TEXT NOT NULL, size INTEGER NOT NULL, preview TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'ready'
);
"""


class SARStore:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.root = private_directory(workspace_root / "sar")
        self.path = self.root / "sar.sqlite3"
        try:
            fd = os.open(
                self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            self.check()
        else:
            os.close(fd)
        with closing(sqlite3.connect(self.path, timeout=3)) as connection:
            current = connection.execute("PRAGMA user_version").fetchone()[0]
            if current not in (0, SCHEMA_VERSION):
                raise WebError(
                    409, "sar_schema", "SAR database version is not supported."
                )
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()

    def check(self) -> None:
        info = self.path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise WebError(
                409, "sar_storage", "SAR database must be a private regular file."
            )

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        self.check()
        connection = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=3000")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()


def dataset_row(connection: sqlite3.Connection, identifier: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM datasets WHERE id=? AND deleted=0", (identifier,)
    ).fetchone()
    if row is None:
        raise WebError(404, "sar_dataset_missing", "SAR dataset is unavailable.")
    return row


def job_row(connection: sqlite3.Connection, identifier: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM jobs WHERE id=? AND deleted=0", (identifier,)
    ).fetchone()
    if row is None:
        raise WebError(404, "sar_job_missing", "SAR analysis task is unavailable.")
    dataset_row(connection, row["dataset_id"])
    return row
