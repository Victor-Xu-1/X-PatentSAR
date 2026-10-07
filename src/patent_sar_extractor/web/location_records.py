"""One bounded file-location record inside the existing environment database."""

from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .errors import WebError

MAX_LOCATION_ROOTS = 128
LOCATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_settings (
 id INTEGER PRIMARY KEY CHECK(id=1), upload_root TEXT NOT NULL, result_root TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS file_roots (
 kind TEXT NOT NULL CHECK(kind IN ('uploads','results')), path TEXT NOT NULL,
 PRIMARY KEY(kind,path)
);
"""


@dataclass(frozen=True)
class LocationRecord:
    upload_root: str
    result_root: str
    roots: tuple[tuple[str, str], ...]


def default_locations(state_root: Path) -> LocationRecord:
    upload, result = str(state_root / "uploads"), str(state_root / "runs")
    return LocationRecord(upload, result, (("uploads", upload), ("results", result)))


def initialize_locations(connection: sqlite3.Connection, state_root: Path) -> None:
    defaults = default_locations(state_root)
    connection.executescript(LOCATION_SCHEMA)
    connection.execute(
        "INSERT OR IGNORE INTO file_settings VALUES(1,?,?)",
        (defaults.upload_root, defaults.result_root),
    )
    connection.executemany(
        "INSERT OR IGNORE INTO file_roots VALUES(?,?)", defaults.roots
    )


def location_record(connection: sqlite3.Connection) -> LocationRecord:
    row = connection.execute(
        "SELECT upload_root,result_root FROM file_settings WHERE id=1"
    ).fetchone()
    roots = tuple(
        (item[0], item[1])
        for item in connection.execute(
            "SELECT kind,path FROM file_roots ORDER BY kind,path LIMIT ?",
            (MAX_LOCATION_ROOTS + 1,),
        )
    )
    if (
        row is None
        or len(roots) > MAX_LOCATION_ROOTS
        or any(
            kind not in {"uploads", "results"}
            or not isinstance(path, str)
            or not 1 <= len(path) <= 4096
            or not Path(path).is_absolute()
            or str(Path(path)) != path
            or "\\" in path
            or "\x00" in path
            or any(part in {".", ".."} for part in path.split("/"))
            for kind, path in roots
        )
        or ("uploads", row[0]) not in roots
        or ("results", row[1]) not in roots
    ):
        raise WebError(
            409,
            "storage_record",
            "Saved file locations are invalid; no files were changed.",
        )
    return LocationRecord(row[0], row[1], roots)


def read_locations(state_root: Path) -> LocationRecord:
    """Legacy workspaces retain their original roots; reads never initialize state."""
    path = state_root / "environments/environment.sqlite3"
    if not os.path.lexists(path):
        return default_locations(state_root)
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise WebError(
            409,
            "storage_record",
            "File-location state must be private and operator-owned.",
        )
    try:
        with closing(
            sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('file_settings','file_roots')"
                )
            }
            if not names:
                return default_locations(state_root)
            if names != {"file_settings", "file_roots"}:
                raise WebError(
                    409, "storage_record", "Saved file-location state is incomplete."
                )
            return location_record(connection)
    except sqlite3.Error as error:
        raise WebError(
            409, "storage_record", "Saved file locations could not be read safely."
        ) from error
