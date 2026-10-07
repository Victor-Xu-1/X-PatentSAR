"""Recoverable history use cases; originals, artifacts, limits and QA stay intact."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from .analysis_lease import analysis_block, analysis_lease
from .environment_cleanup import environment_cleanup_block
from .errors import WebError
from .history_entries import history_entry, project_status
from .history_environment import EnvironmentHistoryStore
from .history_exports import ExportHistory, register_export
from .history_models import HistoryEntry, HistoryKind, HistoryList
from .history_queries import history_page
from .history_storage import (
    lifecycle_block,
    project_block,
    seal_revision,
    tombstone,
    write_tombstone,
)
from .storage import Store, encode, now

_UUID = re.compile(r"[a-f0-9]{32}")
_SHA = re.compile(r"[a-f0-9]{64}")
_ENV_COLUMNS = "id,request_id,fingerprint,action,component_ids,install_root,spec,status,created_at,started_at,finished_at,identity,cancel_requested,applied"


class HistoryService:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.exports = ExportHistory(store)
        self.environments = EnvironmentHistoryStore(store.root)

    @staticmethod
    def _validate(kind: str, identifier: str | None = None) -> None:
        if kind not in {"project", "job", "export", "environment_operation"}:
            raise WebError(422, "history_kind", "History category is not supported.")
        if identifier is not None and not (
            _SHA if kind == "export" else _UUID
        ).fullmatch(identifier):
            raise WebError(404, "history_not_found", "History record does not exist.")

    def _database(self, kind: HistoryKind):
        return self.environments if kind == "environment_operation" else self.store

    @staticmethod
    def _row(
        connection: sqlite3.Connection, kind: HistoryKind, identifier: str
    ) -> dict[str, Any]:
        table, columns = {
            "project": ("projects", "*"),
            "job": ("jobs", "*"),
            "environment_operation": ("operations", _ENV_COLUMNS),
        }[kind]
        row = connection.execute(
            f"SELECT {columns} FROM {table} WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise WebError(404, "history_not_found", "History record does not exist.")
        result = dict(row)
        if kind == "project":
            result["status"] = project_status(result)
        if kind == "environment_operation":
            result["title"] = (
                "Environment setup"
                if result["action"] == "install"
                else "Environment inspection"
            )
        return result

    def _entry(
        self,
        connection: sqlite3.Connection,
        kind: HistoryKind,
        row: dict[str, Any],
        *,
        check_lease: bool = True,
    ) -> HistoryEntry:
        if kind in {"job", "export"}:
            project = connection.execute(
                "SELECT title FROM projects WHERE id=?", (row["project_id"],)
            ).fetchone()
            if project is not None:
                label = (
                    "Extraction / research task"
                    if kind == "job"
                    else row.get("title", "Saved export")
                )
                row = {**row, "title": f"{project['title']} — {label}"[:250]}
        marker = tombstone(connection, kind, row["id"])
        parent = (
            tombstone(connection, "project", row["project_id"])
            if row.get("project_id")
            else None
        )
        source = None
        if kind == "project":
            blocked = project_block(connection, row["id"])
            if check_lease and blocked is None:
                blocked = analysis_block(self.store.root)
            # Hash the complete retained job facts, not a truncated public job list.
            digest = hashlib.sha256()
            for job in connection.execute(
                "SELECT id,status,created_at,started_at,finished_at,identity,cancel_requested FROM jobs WHERE project_id=? ORDER BY id",
                (row["id"],),
            ):
                digest.update(encode(tuple(job)).encode())
            source = digest.hexdigest()
        elif kind == "environment_operation":
            blocked = environment_cleanup_block(row, self.store.root)
        elif kind == "job":
            blocked = lifecycle_block(row)
        else:
            blocked = None
        return history_entry(
            kind,
            row,
            marker,
            parent=parent,
            blocked=blocked,
            unavailable=row.get("unavailable"),
            source=source,
        )

    def get(self, kind: HistoryKind, identifier: str) -> HistoryEntry:
        self._validate(kind, identifier)
        export = self.exports.get(identifier) if kind == "export" else None
        with self._database(kind).connect() as connection:
            if connection is None:
                raise WebError(
                    404, "history_not_found", "History record does not exist."
                )
            connection.execute("BEGIN")
            return self._entry(
                connection, kind, export or self._row(connection, kind, identifier)
            )

    def list(
        self,
        kind: HistoryKind,
        *,
        project_id: str | None = None,
        deleted: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> HistoryList:
        self._validate(kind)
        if (
            type(page) is not int
            or page < 1
            or type(page_size) is not int
            or not 1 <= page_size <= 100
            or type(deleted) is not bool
            or project_id is not None
            and not _UUID.fullmatch(project_id)
        ):
            raise WebError(
                422,
                "history_query",
                "History pagination or project identity is invalid.",
            )
        if kind == "environment_operation" and project_id is not None:
            raise WebError(
                422,
                "history_query",
                "Environment operations do not belong to a project.",
            )
        exports = self.exports.records(project_id) if kind == "export" else None
        with self._database(kind).connect() as connection:
            if connection is None:
                return HistoryList(items=[], total=0, page=page, page_size=page_size)
            connection.execute("BEGIN")
            if exports is not None:
                entries = [self._entry(connection, kind, row) for row in exports]
                entries = [
                    entry
                    for entry in entries
                    if (entry.deleted_at is not None) == deleted
                ]
                entries.sort(
                    key=lambda entry: (entry.created_at, entry.id), reverse=True
                )
                start = (page - 1) * page_size
                return HistoryList(
                    items=entries[start : start + page_size],
                    total=len(entries),
                    page=page,
                    page_size=page_size,
                )
            identifiers, total = history_page(
                connection,
                kind,
                project_id=project_id,
                deleted=deleted,
                page=page,
                page_size=page_size,
            )
            items = [
                self._entry(connection, kind, self._row(connection, kind, identifier))
                for identifier in identifiers
            ]
        return HistoryList(items=items, total=total, page=page, page_size=page_size)

    def delete(
        self, kind: HistoryKind, identifier: str, expected_revision: str
    ) -> HistoryEntry:
        return self._mutate(kind, identifier, expected_revision, "delete")

    def restore(
        self, kind: HistoryKind, identifier: str, expected_revision: str
    ) -> HistoryEntry:
        return self._mutate(kind, identifier, expected_revision, "restore")

    def _mutate(
        self, kind: HistoryKind, identifier: str, expected_revision: str, action: str
    ) -> HistoryEntry:
        self._validate(kind, identifier)
        if not _SHA.fullmatch(expected_revision):
            raise WebError(
                422, "history_revision", "History revision must be a SHA-256 token."
            )
        export = self.exports.get(identifier) if kind == "export" else None
        lease = analysis_lease(self.store.root) if kind == "project" else nullcontext()
        try:
            with lease, self._database(kind).connect(write=True) as connection:
                assert connection is not None
                row = (
                    self.exports.inspect(export)
                    if export is not None
                    else self._row(connection, kind, identifier)
                )
                entry = self._entry(connection, kind, row, check_lease=False)
                marker = tombstone(connection, kind, identifier)
                desired_deleted = action == "delete"
                already = (entry.deleted_at is not None) == desired_deleted
                replay = (
                    already
                    and marker.get("action") == action
                    and marker.get("previous_revision") == expected_revision
                    and marker.get("applied_revision") == entry.revision
                )
                if expected_revision != entry.revision and not replay:
                    raise WebError(
                        409,
                        "history_conflict",
                        "History changed; refresh its current revision before changing visibility.",
                    )
                parent = (
                    tombstone(connection, "project", row["project_id"])
                    if row.get("project_id")
                    else None
                )
                if parent and parent["deleted_at"] is not None:
                    raise WebError(
                        409,
                        "history_parent_deleted",
                        "Restore the parent project first.",
                    )
                if already:
                    return entry
                if not (entry.can_delete if desired_deleted else entry.can_restore):
                    raise WebError(
                        409,
                        "history_blocked",
                        entry.blocked_reason
                        or "This record cannot change visibility safely.",
                    )
                if export is not None:
                    register_export(
                        connection,
                        row["project_id"],
                        Path(row["path"]),
                        row["created_at"],
                    )
                write_tombstone(
                    connection,
                    kind,
                    identifier,
                    now() if desired_deleted else None,
                    expected_revision,
                    action,
                )
                result = self._entry(connection, kind, row, check_lease=False)
                seal_revision(connection, kind, identifier, result.revision)
                return result
        except WebError as error:
            if kind == "project" and error.code in {"analysis_busy", "analysis_lock"}:
                raise WebError(
                    409,
                    "history_blocked",
                    "The shared analysis lease is active or cannot be verified safely; no visibility was changed.",
                ) from error
            raise
