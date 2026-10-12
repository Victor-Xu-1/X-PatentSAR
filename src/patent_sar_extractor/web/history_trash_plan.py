"""Whole-category snapshot with existing lifecycle/source gates, never a page sample."""

from __future__ import annotations

import hashlib
from contextlib import nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .analysis_lease import analysis_block
from .environment_cleanup import environment_cleanup_block
from .errors import WebError
from .history_asset_models import CleanupManifest
from .history_models import HistoryKind
from .history_purge_models import HISTORY_KINDS, MAX_TRASH_RECORDS, TrashPlan
from .history_purge_storage import permanently_removed
from .history_queries import history_page
from .history_storage import lifecycle_block, project_block
from .storage import encode

if TYPE_CHECKING:
    from .history_service import HistoryService


@dataclass(frozen=True, slots=True)
class TrashSnapshot:
    plan: TrashPlan
    entries: tuple[tuple[HistoryKind, str, str], ...]
    assets: CleanupManifest | None = None


def trash_snapshot(
    history: HistoryService, *, held_lease=False, workspace_connection=None
) -> TrashSnapshot:
    counts = dict.fromkeys(HISTORY_KINDS, 0)
    entries, blocked = [], 0
    exports = history.exports.records()
    for kind in HISTORY_KINDS:
        database = (
            nullcontext(workspace_connection)
            if workspace_connection is not None and kind != "environment_operation"
            else history._database(kind).connect()
        )
        with database as connection:
            if connection is None:
                continue
            if connection is not workspace_connection:
                connection.execute("BEGIN")
            if kind == "export":
                rows = exports
            else:
                identifiers, total = history_page(
                    connection,
                    kind,
                    project_id=None,
                    deleted=True,
                    page=1,
                    page_size=MAX_TRASH_RECORDS + 1,
                )
                if total > MAX_TRASH_RECORDS:
                    raise WebError(
                        413,
                        "history_trash_limit",
                        "The complete recycle bin exceeds its bounded clear limit; nothing was omitted or changed.",
                    )
                rows = [
                    history._row(connection, kind, identifier)
                    for identifier in identifiers
                ]
            for row in rows:
                if permanently_removed(
                    connection, kind, row["id"], row.get("project_id")
                ):
                    continue
                entry = history._entry(connection, kind, row, check_lease=False)
                if entry.deleted_at is None:
                    continue
                if len(entries) == MAX_TRASH_RECORDS:
                    raise WebError(
                        413,
                        "history_trash_limit",
                        "The complete recycle bin exceeds its bounded clear limit; nothing was omitted or changed.",
                    )
                reason = None
                if kind == "project":
                    reason = project_block(connection, row["id"])
                    if not held_lease and reason is None:
                        reason = analysis_block(history.store.root)
                elif kind == "job":
                    reason = lifecycle_block(row)
                elif kind == "environment_operation":
                    reason = environment_cleanup_block(row, history.store.root)
                blocked += int(reason is not None)
                counts[kind] += 1
                entries.append((kind, row["id"], entry.revision))
    entries.sort()
    from .history_asset_inventory import inventory

    preliminary = TrashSnapshot(
        TrashPlan(
            revision="0" * 64, total=len(entries), counts=counts, blocked=blocked
        ),
        tuple(entries),
    )
    with (
        nullcontext(workspace_connection)
        if workspace_connection is not None
        else history.store.connect()
    ) as connection:
        assets = inventory(history, preliminary, connection)
    revision = hashlib.sha256(
        encode(
            ["history.trash-plan.v2", entries, counts, blocked, assets.model_dump()]
        ).encode()
    ).hexdigest()
    return TrashSnapshot(
        TrashPlan(
            revision=revision,
            total=len(entries),
            counts=counts,
            blocked=blocked,
            files_total=len(assets.files),
            bytes_total=assets.size_bytes,
            retained_targets=assets.retained_targets,
        ),
        tuple(entries),
        assets,
    )
