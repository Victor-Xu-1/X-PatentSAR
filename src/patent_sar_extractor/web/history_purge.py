"""One all-type clear with atomic intent and bounded unreferenced-file cleanup."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from .analysis_lease import analysis_lease
from .errors import WebError
from .history_asset_cleanup import continue_cleanup, pending_receipt, prepare_cleanup
from .history_guard import history_guard
from .history_purge_models import TrashClearReceipt, TrashClearRequest, TrashPlan
from .history_trash_plan import trash_snapshot
from .storage import encode, now

if TYPE_CHECKING:
    from .history_service import HistoryService


class TrashPurge:
    def __init__(self, history: HistoryService) -> None:
        self.history = history

    def plan(self) -> TrashPlan:
        with history_guard(self.history.store.root, create=False):
            plan = trash_snapshot(self.history).plan
            plan.pending = pending_receipt(self.history.store)
            return plan

    def receipt(self, request_id: str) -> TrashClearReceipt:
        with self.history.store.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM history_purge_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise WebError(
                404,
                "history_clear_not_found",
                "No completed clear receipt exists for this request. No write was repeated.",
            )
        return TrashClearReceipt.model_validate_json(row[0])

    def clear(self, request: TrashClearRequest) -> TrashClearReceipt:
        store = self.history.store
        fingerprint = hashlib.sha256(encode(request.model_dump()).encode()).hexdigest()
        with history_guard(store.root):
            with store.connect() as connection:
                previous = connection.execute(
                    "SELECT fingerprint,payload FROM history_purge_requests WHERE request_id=?",
                    (request.request_id,),
                ).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise WebError(
                        409,
                        "history_clear_request_conflict",
                        "The same clear request cannot be reused for different records.",
                    )
                receipt = TrashClearReceipt.model_validate_json(previous["payload"])
                if receipt.status == "complete":
                    return receipt
                with analysis_lease(store.root):
                    return continue_cleanup(store, request.request_id)
            if pending_receipt(store) is not None:
                raise WebError(
                    409,
                    "history_cleanup_pending",
                    "Continue the saved file cleanup before starting another clear operation.",
                )
            with analysis_lease(store.root):
                self._publish(request, fingerprint)
                return continue_cleanup(store, request.request_id)

    def _publish(self, request, fingerprint):
        store = self.history.store
        with store.connect(write=True) as connection:
            snapshot = trash_snapshot(
                self.history, held_lease=True, workspace_connection=connection
            )
            plan = snapshot.plan
            if (
                plan.revision != request.expected_revision
                or plan.total != request.expected_total
            ):
                raise WebError(
                    409,
                    "history_clear_conflict",
                    "The recycle bin changed. Review a fresh complete count before confirming again.",
                )
            if plan.blocked:
                raise WebError(
                    409,
                    "history_clear_blocked",
                    "A trashed record is active or retains unverified ownership. Nothing was permanently removed.",
                )
            stamp = now()
            receipt = TrashClearReceipt(
                request_id=request.request_id,
                plan_revision=plan.revision,
                cleared=plan.total,
                counts=plan.counts,
                started_at=stamp,
                status="cleanup_pending",
                files_total=len(snapshot.assets.files),
                retained_targets=snapshot.assets.retained_targets,
            )
            connection.executemany(
                "INSERT INTO history_purged_entries(kind,id,purged_at,request_id) VALUES(?,?,?,?)",
                [
                    (kind, identifier, stamp, request.request_id)
                    for kind, identifier, _ in snapshot.entries
                ],
            )
            connection.execute(
                "INSERT INTO history_purge_requests(request_id,fingerprint,payload) VALUES(?,?,?)",
                (request.request_id, fingerprint, encode(receipt.model_dump())),
            )
            prepare_cleanup(connection, request.request_id, snapshot.assets)
