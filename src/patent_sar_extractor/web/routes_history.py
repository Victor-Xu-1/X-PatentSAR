"""Thin authenticated API-v1 adapters for recoverable trash, never purge."""

from __future__ import annotations

from fastapi import APIRouter, Query

from .history_models import HistoryEntry, HistoryKind, HistoryList, HistoryMutation
from .history_service import HistoryService


def history_routes(service: HistoryService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/history")

    @router.get("", response_model=HistoryList)
    def listing(
        kind: HistoryKind,
        project_id: str | None = Query(default=None, pattern=r"^[a-f0-9]{32}$"),
        deleted: bool = False,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=100),
    ) -> HistoryList:
        return service.list(
            kind, project_id=project_id, deleted=deleted, page=page, page_size=page_size
        )

    @router.get("/{kind}/{identifier}", response_model=HistoryEntry)
    def record(kind: HistoryKind, identifier: str) -> HistoryEntry:
        return service.get(kind, identifier)

    @router.post("/{kind}/{identifier}/delete", response_model=HistoryEntry)
    def delete(
        kind: HistoryKind, identifier: str, body: HistoryMutation
    ) -> HistoryEntry:
        return service.delete(kind, identifier, body.expected_revision)

    @router.post("/{kind}/{identifier}/restore", response_model=HistoryEntry)
    def restore(
        kind: HistoryKind, identifier: str, body: HistoryMutation
    ) -> HistoryEntry:
        return service.restore(kind, identifier, body.expected_revision)

    return router
