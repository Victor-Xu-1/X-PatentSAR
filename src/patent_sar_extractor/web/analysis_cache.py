"""Private, bounded, rebuildable analysis cache. No main schema migrations."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from pathlib import Path

from .errors import WebError
from .files import private_directory
from .storage import encode, now

SCHEMA_VERSION = 1
MAX_ENTRY_BYTES = 1024 * 1024
MAX_CACHE_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 5000


def cache_key(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


class AnalysisCache:
    def __init__(self, state_root: Path) -> None:
        self.root = private_directory(state_root / "analysis")
        self.path = self.root / "cache.sqlite3"
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
                    "unsafe_analysis_cache",
                    "Analysis cache must be a private regular file.",
                )
        else:
            os.close(fd)
        try:
            with sqlite3.connect(self.path, timeout=2) as connection:
                current = connection.execute("PRAGMA user_version").fetchone()[0]
                if current not in (0, SCHEMA_VERSION):
                    raise WebError(
                        409,
                        "analysis_schema",
                        "Analysis cache schema is unsupported; preserve it before rebuilding.",
                    )
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS analysis_cache "
                    "(kind TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL, "
                    "created_at TEXT NOT NULL, PRIMARY KEY(kind,key))"
                )
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        except sqlite3.Error as exc:
            raise WebError(
                503,
                "analysis_cache_error",
                "Analysis cache could not be opened safely.",
            ) from exc

    def get(self, kind: str, key: str) -> object | None:
        try:
            with sqlite3.connect(self.path, timeout=2) as connection:
                row = connection.execute(
                    "SELECT payload FROM analysis_cache WHERE kind=? AND key=?",
                    (kind, key),
                ).fetchone()
            if row is None:
                return None
            if len(row[0].encode()) > MAX_ENTRY_BYTES:
                raise ValueError("Oversized cache record")
            return json.loads(row[0], parse_constant=_reject_constant)
        except (sqlite3.Error, ValueError, UnicodeError, RecursionError) as exc:
            raise WebError(
                503,
                "analysis_cache_error",
                "Analysis cache contains invalid data; preserve it before rebuilding.",
            ) from exc

    def put(self, kind: str, key: str, payload: object) -> None:
        content = encode(payload)
        if len(content.encode()) > MAX_ENTRY_BYTES:
            raise WebError(
                502,
                "analysis_output_limit",
                "Analysis result exceeds its cache size limit.",
            )
        try:
            with sqlite3.connect(
                self.path, timeout=2, isolation_level=None
            ) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT OR REPLACE INTO analysis_cache VALUES(?,?,?,?)",
                    (kind, key, content, now()),
                )
                # Prune oldest rebuildable records transactionally, never original artifacts.
                rows = connection.execute(
                    "SELECT rowid,length(CAST(payload AS BLOB)) FROM analysis_cache "
                    "ORDER BY created_at DESC,rowid DESC"
                ).fetchall()
                used = 0
                remove = []
                for index, (rowid, size) in enumerate(rows):
                    used += size
                    if index >= MAX_ENTRIES or used > MAX_CACHE_BYTES:
                        remove.append((rowid,))
                connection.executemany(
                    "DELETE FROM analysis_cache WHERE rowid=?", remove
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise WebError(
                503,
                "analysis_cache_error",
                "Analysis cache write failed; no original data was changed.",
            ) from exc


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite cache value")
