"""Thin study adapters on the SAR session/CSRF, queue and asset boundaries."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from .models import SARJob
from .study_admission import profile
from .study_exports import export_study
from .study_models import (
    StudyDrawing,
    StudyOverview,
    StudyProfile,
    StudyRequest,
    StudyRows,
)
from .study_results import StudyResults


def study_routes(service, queue) -> APIRouter:
    router = APIRouter()
    reads = asyncio.Semaphore(2)

    @router.get("/datasets/{identifier}/profile", response_model=StudyProfile)
    async def dataset_profile(identifier: str):
        async with reads:
            return await asyncio.to_thread(profile, service(), identifier)

    @router.post(
        "/datasets/{identifier}/studies", response_model=SARJob, status_code=202
    )
    def start(identifier: str, body: StudyRequest):
        return queue().study(identifier, body)

    @router.get("/jobs/{identifier}/study", response_model=StudyOverview)
    async def overview(identifier: str):
        async with reads:
            return await asyncio.to_thread(StudyResults(queue()).overview, identifier)

    @router.get("/jobs/{identifier}/study/rows", response_model=StudyRows)
    async def rows(
        identifier: str,
        page: int = 1,
        page_size: int = 50,
        query: str = "",
        scope: str = "all",
        scaffold_id: str = "",
        region_id: str = "",
        fragment_id: str = "",
        sort_by: str = "label",
        sort_direction: str = "asc",
    ):
        async with reads:
            return await asyncio.to_thread(
                StudyResults(queue()).rows,
                identifier,
                page,
                page_size,
                query,
                scope,
                scaffold_id,
                region_id,
                fragment_id,
                sort_by,
                sort_direction,
            )

    @router.get("/jobs/{job_id}/study/drawing", response_model=StudyDrawing)
    async def drawing(job_id: str, kind: str, identifier: str, region_id: str = ""):
        async with reads:
            return await asyncio.to_thread(
                StudyResults(queue()).drawing, job_id, kind, identifier, region_id
            )

    @router.get("/jobs/{identifier}/study/export")
    async def export(identifier: str, format: str = "json"):
        async with reads:
            content, media_type = await asyncio.to_thread(
                export_study, queue(), identifier, format
            )
        return StreamingResponse(
            content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="SAR-study-{identifier}.{format}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
