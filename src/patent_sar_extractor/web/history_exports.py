"""Bounded direct-file discovery of first-party exports; no import or byte reads."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import WebError
from .files import directory_descriptor
from .saved_exports import MAX_EXPORT_BYTES
from .storage import Store

MAX_SCAN_ENTRIES = 10000
MAX_SCAN_DIRECTORIES = 25600  # 200 projects * at most 128 recorded roots.
EXPORT_NAME = re.compile(r"[a-f0-9]{32}\.(csv|json)")
PROJECT_ID = re.compile(r"[a-f0-9]{32}")


def export_id(path: Path) -> str:
    return hashlib.sha256(str(path).encode()).hexdigest()


def register_export(
    connection: sqlite3.Connection, project_id: str, path: Path, stamp: str
) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO history_exports(id,project_id,path,created_at) VALUES(?,?,?,?)",
        (export_id(path), project_id, str(path), stamp),
    )


class ExportHistory:
    def __init__(self, store: Store) -> None:
        self.store = store

    def _root_problems(self, roots: tuple[Path, ...]) -> dict[Path, str]:
        problems = {}
        policy = self.store.locations.policy
        for root in roots:
            try:
                policy.validate("results", str(root))
            except WebError:
                problems[root] = (
                    "The recorded result root no longer passes workspace ownership, purpose or native-location checks. Its files were not adopted or changed."
                )
        return problems

    def _allowed(self, row: dict[str, Any], roots: tuple[Path, ...]) -> bool:
        raw = row["path"]
        path = Path(raw)
        return bool(
            PROJECT_ID.fullmatch(row["project_id"])
            and path.is_absolute()
            and str(path) == raw
            and "\\" not in raw
            and "\x00" not in raw
            and not any(part in {".", ".."} for part in raw.split("/"))
            and path.parent.name == "exports"
            and path.parent.parent.name == row["project_id"]
            and path.parent.parent.parent in roots
            and EXPORT_NAME.fullmatch(path.name)
            and export_id(path) == row["id"]
        )

    def inspect(
        self,
        row: dict[str, Any],
        roots: tuple[Path, ...] | None = None,
        problems: dict[Path, str] | None = None,
    ) -> dict[str, Any]:
        roots = self.store.locations.roots("results") if roots is None else roots
        problems = self._root_problems(roots) if problems is None else problems
        result = {
            **row,
            "title": "Saved " + Path(row["path"]).suffix[1:].upper() + " export",
            "status": "available",
            "size_bytes": None,
            "file_identity": None,
            "unavailable": None,
        }
        if not self._allowed(row, roots):
            result.update(
                status="unavailable",
                unavailable="The saved export location is no longer a valid recorded first-party location.",
            )
            return result
        root_problem = problems.get(Path(row["path"]).parent.parent.parent)
        if root_problem:
            result.update(status="unavailable", unavailable=root_problem)
            return result
        descriptor = None
        try:
            descriptor = directory_descriptor(Path(row["path"]).parent)
            info = os.stat(
                Path(row["path"]).name, dir_fd=descriptor, follow_symlinks=False
            )
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
            ):
                raise ValueError("not a regular owned export")
            result["size_bytes"] = info.st_size
            result["file_identity"] = [
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            ]
            if info.st_size > MAX_EXPORT_BYTES:
                raise ValueError("export exceeds byte bound")
        except FileNotFoundError:
            result.update(
                status="missing",
                unavailable="The retained export file is missing; restoring its visibility cannot recreate its bytes.",
            )
        except (OSError, ValueError):
            result.update(
                status="unavailable",
                unavailable="The retained export file is unsafe or unavailable; no file was read or changed.",
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return result

    def records(self, project_id: str | None = None) -> list[dict[str, Any]]:
        roots = self.store.locations.roots("results")
        problems = self._root_problems(roots)
        with self.store.connect() as connection:
            projects = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM projects WHERE (? IS NULL OR id=?)",
                    (project_id, project_id),
                )
            ]
            saved = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM history_exports WHERE (? IS NULL OR project_id=?) LIMIT ?",
                    (project_id, project_id, MAX_SCAN_ENTRIES + 1),
                )
            ]
        if (
            len(saved) > MAX_SCAN_ENTRIES
            or len(projects) * len(roots) > MAX_SCAN_DIRECTORIES
        ):
            raise WebError(
                413,
                "history_export_limit",
                "Saved export inventory exceeds its bounded scan limit; no records were silently omitted.",
            )
        result = {row["id"]: self.inspect(row, roots, problems) for row in saved}
        for root in problems:
            if not any(Path(row["path"]).parent.parent.parent == root for row in saved):
                raise WebError(
                    409,
                    "history_export_storage",
                    "A recorded result root is no longer owned by this workspace. Unknown files were not adopted or changed.",
                )
        visited = 0
        for project in projects:
            if not PROJECT_ID.fullmatch(project):
                continue
            for root in roots:
                if root in problems:
                    continue
                directory = root / project / "exports"
                try:
                    descriptor = directory_descriptor(directory)
                except (FileNotFoundError, NotADirectoryError):
                    continue
                except OSError as error:
                    raise WebError(
                        409,
                        "history_export_storage",
                        "A registered export directory could not be inspected safely.",
                    ) from error
                try:
                    with os.scandir(descriptor) as children:
                        for child in children:
                            visited += 1
                            if visited > MAX_SCAN_ENTRIES:
                                raise WebError(
                                    413,
                                    "history_export_limit",
                                    "Export scan reached its safe entry limit; no records were silently omitted.",
                                )
                            if not EXPORT_NAME.fullmatch(child.name):
                                continue
                            info = child.stat(follow_symlinks=False)
                            if (
                                not stat.S_ISREG(info.st_mode)
                                or info.st_uid != os.getuid()
                                or info.st_nlink != 1
                            ):
                                continue
                            path = directory / child.name
                            identifier = export_id(path)
                            if identifier not in result:
                                row = {
                                    "id": identifier,
                                    "project_id": project,
                                    "path": str(path),
                                    "created_at": datetime.fromtimestamp(
                                        info.st_mtime, UTC
                                    ).isoformat(),
                                }
                                result[identifier] = self.inspect(row, roots, problems)
                except OSError as error:
                    raise WebError(
                        409,
                        "history_export_storage",
                        "Export metadata changed or became unavailable during discovery.",
                    ) from error
                finally:
                    os.close(descriptor)
        if len(result) > MAX_SCAN_ENTRIES:
            raise WebError(
                413,
                "history_export_limit",
                "Saved export inventory exceeds its safe bound; no records were silently omitted.",
            )
        return list(result.values())

    def get(self, identifier: str) -> dict[str, Any]:
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT * FROM history_exports WHERE id=?", (identifier,)
            ).fetchone()
        if row:
            return self.inspect(dict(row))
        result = next((row for row in self.records() if row["id"] == identifier), None)
        if result is None:
            raise WebError(
                404,
                "history_export_missing",
                "Saved export is missing or was never discoverable in a recorded first-party location.",
            )
        return result
