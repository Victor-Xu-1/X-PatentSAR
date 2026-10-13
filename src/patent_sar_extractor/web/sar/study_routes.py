"""Thin study adapters on the SAR session/CSRF, queue and asset boundaries."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Query
from starlette.responses import StreamingResponse

from .indicator_models import IndicatorProfile
from .matrix_models import StudyMatrix
from .models import SARJob
from .preview_models import StudyPreview
from .study_admission import profile
from .study_catalog_models import StudyCatalog, StudyRegionDetail
from .study_exports import export_study
from .study_models import (
    StudyDrawing,
    StudyRequest,
    StudyRows,
)
from .study_results import StudyResults
from .study_view_models import CurrentStudyOverview


def study_routes(service, queue) -> APIRouter:
    router = APIRouter()
    reads = asyncio.Semaphore(2)

    @router.get("/datasets/{identifier}/profile", response_model=IndicatorProfile)
    async def dataset_profile(identifier: str):
        async with reads:
            return await asyncio.to_thread(profile, service(), identifier)

    @router.post(
        "/datasets/{identifier}/studies", response_model=SARJob, status_code=202
    )
    def start(identifier: str, body: StudyRequest):
        return queue().study(identifier, body)

    @router.get("/jobs/{identifier}/study", response_model=CurrentStudyOverview)
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
        reference_id: str = "",
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
                reference_id,
            )

    @router.get("/jobs/{identifier}/study/catalog", response_model=StudyCatalog)
    async def catalog(identifier: str):
        async with reads:
            return await asyncio.to_thread(StudyResults(queue()).catalog, identifier)

    @router.get(
        "/jobs/{identifier}/study/regions/{region_id}", response_model=StudyRegionDetail
    )
    async def region_detail(identifier: str, region_id: str):
        async with reads:
            return await asyncio.to_thread(
                StudyResults(queue()).region, identifier, region_id
            )

    @router.get("/jobs/{job_id}/study/drawing", response_model=StudyDrawing)
    async def drawing(job_id: str, kind: str, identifier: str, region_id: str = ""):
        async with reads:
            return await asyncio.to_thread(
                StudyResults(queue()).drawing, job_id, kind, identifier, region_id
            )

    @router.get("/jobs/{identifier}/study/preview", response_model=StudyPreview)
    async def transformation_preview(identifier: str, region_id: str, molecule_id: str):
        from .study_preview import preview

        async with reads:
            return await asyncio.to_thread(
                preview, queue(), identifier, region_id, molecule_id
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

    @router.get("/jobs/{identifier}/study/matrix", response_model=StudyMatrix)
    async def comparison_matrix(
        identifier: str,
        reference_id: str,
        region_id: Annotated[list[str] | None, Query(max_length=6)] = None,
        molecule_id: Annotated[list[str] | None, Query(max_length=6)] = None,
    ):
        from .study_matrix import matrix

        async with reads:
            return await asyncio.to_thread(
                matrix,
                queue(),
                identifier,
                reference_id,
                region_id or [],
                molecule_id or [],
            )

    return router
