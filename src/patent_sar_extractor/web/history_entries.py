"""Truthful metadata DTOs and opaque compare-and-set revisions, without model IO."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .errors import WebError
from .history_models import HistoryEntry, HistoryKind
from .storage import encode


def project_status(row: dict[str, Any]) -> str:
    try:
        snapshot = json.loads(row["snapshot"])
        return str(snapshot.get("acceptance", {}).get("state", "not_run"))[:40]
    except (ValueError, TypeError, AttributeError) as error:
        raise WebError(
            409,
            "history_record",
            "Project metadata is invalid; original evidence was preserved.",
        ) from error


def history_entry(
    kind: HistoryKind,
    row: dict[str, Any],
    marker: dict[str, Any],
    *,
    parent: dict[str, Any] | None = None,
    blocked: str | None = None,
    unavailable: str | None = None,
    source: object = None,
) -> HistoryEntry:
    parent = parent or {"deleted_at": None, "generation": 0}
    deleted_at = marker["deleted_at"] or parent["deleted_at"]
    parent_deleted = parent["deleted_at"] is not None
    if parent_deleted:
        reason = (
            "Restore the parent project before restoring or removing this child record."
        )
    else:
        reason = blocked or unavailable
    revision = hashlib.sha256(
        encode(
            [
                kind,
                row,
                marker.get("generation", 0),
                marker["deleted_at"],
                parent.get("generation", 0),
                parent["deleted_at"],
                source,
            ]
        ).encode()
    ).hexdigest()
    project_id = row["id"] if kind == "project" else row.get("project_id")
    return HistoryEntry(
        kind=kind,
        id=row["id"],
        project_id=project_id,
        title=(
            row.get("title")
            or {
                "job": "Extraction / research task",
                "export": "Saved export",
                "environment_operation": "Environment operation",
            }.get(kind, "Project")
        )[:250],
        status=row.get("status", "not_run"),
        created_at=row["created_at"],
        deleted_at=deleted_at,
        revision=revision,
        can_delete=deleted_at is None and blocked is None,
        can_restore=deleted_at is not None
        and not parent_deleted
        and blocked is None
        and unavailable is None,
        blocked_reason=reason,
        size_bytes=row.get("size_bytes"),
    )
