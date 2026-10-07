"""Access existing environment history without initializing settings or readiness."""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import WebError
from .history_storage import ENVIRONMENT_SCHEMA


class EnvironmentHistoryStore:
    def __init__(self, state_root: Path) -> None:
        self.path = state_root / "environments/environment.sqlite3"

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection | None]:
        if not os.path.lexists(self.path):
            if write:
                raise WebError(
                    404, "history_not_found", "No saved environment operation exists."
                )
            yield None
            return
        info = self.path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or any(path.is_symlink() for path in self.path.parents)
        ):
            raise WebError(
                409,
                "environment_record",
                "Environment history must remain private and operator-owned.",
            )
        connection = sqlite3.connect(
            self.path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
            uri=True,
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise WebError(
                    409,
                    "environment_schema",
                    "Environment history version is not supported.",
                )
            if write:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(ENVIRONMENT_SCHEMA.strip())
            else:
                connection.execute("PRAGMA query_only=ON")
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()
