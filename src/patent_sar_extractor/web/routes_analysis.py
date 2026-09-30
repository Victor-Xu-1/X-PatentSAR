"""Authenticated additive routes; share the main app's session/CSRF boundary."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, Request

from .analysis import AnalysisService
from .analysis_models import (
    ADMETRequest,
    ADMETResponse,
    EvidenceSummary,
    RecognitionRequest,
    RecognitionResponse,
)
from .errors import WebError
from .service import WorkspaceService

T = TypeVar("T")


async def _cancellable(request: Request, operation: Callable[..., T], *args: Any) -> T:
    cancel = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(operation, *args, cancel=cancel))
    try:
        while not task.done():
            if await request.is_disconnected():
                cancel.set()
            await asyncio.wait({task}, timeout=0.1)
        return await task
    except asyncio.CancelledError:
        cancel.set()
        # Do not release request ownership before the thread's cleanup has run.
        try:
            await asyncio.shield(asyncio.wait_for(task, timeout=3))
        except (WebError, TimeoutError, asyncio.CancelledError):
            # The worker logs its outcome and retains its gate until actual cleanup.
            task.add_done_callback(_consume_finished)
        raise


def _consume_finished(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()  # Retrieve an abandoned request's already-logged outcome.


def analysis_routes(
    service: WorkspaceService, analysis_service: AnalysisService
) -> APIRouter:
    """Register before the main SPA catch-all, and close in its existing lifespan."""
    if analysis_service.workspace is not service:
        raise WebError(
            400,
            "analysis_workspace",
            "Analysis routes must use the same workspace service.",
        )
    router = APIRouter(prefix="/api/v1")

    @router.post("/analysis/admet", response_model=ADMETResponse)
    async def admet(request: Request, body: ADMETRequest) -> ADMETResponse:
        return await _cancellable(request, analysis_service.admet, body.smiles)

    @router.post(
        "/projects/{project_id}/compounds/{compound_id}/recognize",
        response_model=RecognitionResponse,
    )
    async def recognize(
        project_id: str, compound_id: str, request: Request, body: RecognitionRequest
    ) -> RecognitionResponse:
        return await _cancellable(
            request, analysis_service.recognize, project_id, compound_id
        )

    @router.get(
        "/projects/{project_id}/evidence-summary", response_model=EvidenceSummary
    )
    def evidence_summary(project_id: str) -> EvidenceSummary:
        return analysis_service.evidence_summary(project_id)

    return router
