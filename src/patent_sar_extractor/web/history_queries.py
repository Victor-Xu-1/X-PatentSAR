"""Full-history SQL pagination, independent of bounded recent/catalog lists."""

from __future__ import annotations

import sqlite3
from typing import Any

from .history_models import HistoryKind


def history_page(
    connection: sqlite3.Connection,
    kind: HistoryKind,
    *,
    project_id: str | None,
    deleted: bool,
    page: int,
    page_size: int,
) -> tuple[list[str], int]:
    table = {
        "project": "projects",
        "job": "jobs",
        "environment_operation": "operations",
    }[kind]
    has_markers = (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='history_tombstones'"
        ).fetchone()
        is not None
    )
    joins, state = "", "0"
    if has_markers:
        joins = " LEFT JOIN history_tombstones t ON t.id=r.id AND t.kind=?"
        state = "t.deleted_at IS NOT NULL"
        if kind == "job":
            joins += " LEFT JOIN history_tombstones p ON p.id=r.project_id AND p.kind='project'"
            state = "(t.deleted_at IS NOT NULL OR p.deleted_at IS NOT NULL)"
    parameters: list[Any] = [kind] if has_markers else []
    condition = f"({state})=?"
    parameters.append(int(deleted))
    if project_id is not None:
        condition += " AND " + ("r.id=?" if kind == "project" else "r.project_id=?")
        parameters.append(project_id)
    query = f"FROM {table} r{joins} WHERE {condition}"
    total = connection.execute("SELECT COUNT(*) " + query, parameters).fetchone()[0]
    identifiers = [
        row[0]
        for row in connection.execute(
            "SELECT r.id "
            + query
            + " ORDER BY r.created_at DESC,r.rowid DESC LIMIT ? OFFSET ?",
            (*parameters, page_size, (page - 1) * page_size),
        )
    ]
    return identifiers, total
