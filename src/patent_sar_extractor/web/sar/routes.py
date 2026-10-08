"""Thin authenticated SAR module adapters; the main extraction routes are unchanged."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request
from starlette.responses import Response, StreamingResponse

from ..errors import WebError
from .csv_reader import MAX_CSV_BYTES
from .exports import export_csv, export_json
from .feature import SARFeature
from .models import (
    AnalysisRequest,
    CSVMapping,
    CSVPreview,
    Dataset,
    DatasetList,
    JobList,
    Molecule,
    MoleculeDrawing,
    MoleculePage,
    PairPage,
    ProjectSnapshot,
    Region,
    RegionRequest,
    ResumeRequest,
    SARJob,
)
from .queue import SARQueue
from .service import SARService


def sar_routes(feature: SARFeature) -> APIRouter:
    router = APIRouter(prefix="/api/v1/sar")
    uploads = asyncio.Semaphore(2)

    def srv() -> SARService:
        return feature.require()[0]

    def q() -> SARQueue:
        return feature.require()[1]

    @router.get("/datasets", response_model=DatasetList)
    def datasets():
        return srv().list()

    @router.post("/csv/preview", response_model=CSVPreview)
    async def csv_preview(
        request: Request, filename: str = Query(min_length=1, max_length=200)
    ):
        async with uploads:
            data = bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > MAX_CSV_BYTES:
                    raise WebError(
                        413,
                        "sar_csv_limit",
                        "CSV exceeds 8 MiB; no dataset was created.",
                    )
            return await asyncio.to_thread(srv().uploads.create, bytes(data), filename)

    @router.delete("/csv/{token}", status_code=204)
    def remove_preview(token: str):
        srv().uploads.remove(token)
        return Response(status_code=204)

    @router.post("/datasets/csv", response_model=Dataset, status_code=201)
    def csv_dataset(body: CSVMapping):
        return srv().from_csv(body)

    @router.post("/datasets/project", response_model=Dataset, status_code=201)
    def project_dataset(body: ProjectSnapshot):
        return srv().from_project(body)

    @router.get("/datasets/{identifier}", response_model=Dataset)
    def dataset(identifier: str):
        return srv().dataset(identifier)

    @router.delete("/datasets/{identifier}", status_code=204)
    def remove_dataset(identifier: str):
        if q().retained_lease is not None:
            raise WebError(
                409,
                "sar_process_unverified",
                "Verify SAR worker cleanup before removing data.",
            )
        srv().datasets.remove(identifier)
        return Response(status_code=204)

    @router.get("/datasets/{identifier}/molecules", response_model=MoleculePage)
    def molecules(identifier: str, page: int = 1, page_size: int = 50, query: str = ""):
        return srv().datasets.page(identifier, page, page_size, query)

    @router.get(
        "/datasets/{identifier}/molecules/{molecule_id}/drawing",
        response_model=MoleculeDrawing,
    )
    def drawing(identifier: str, molecule_id: str):
        return srv().drawing(identifier, molecule_id)

    @router.get(
        "/datasets/{identifier}/molecules/{molecule_id}", response_model=Molecule
    )
    def molecule_metadata(identifier: str, molecule_id: str):
        return srv().datasets.molecule(identifier, molecule_id)

    @router.post(
        "/datasets/{identifier}/regions", response_model=Region, status_code=201
    )
    def region(identifier: str, body: RegionRequest):
        return srv().save_region(identifier, body)

    @router.get("/datasets/{identifier}/jobs", response_model=JobList)
    def jobs(identifier: str):
        result = q().jobs.list(identifier)
        result.items = [q().view(item.id) for item in result.items]
        return result

    @router.post("/datasets/{identifier}/jobs", response_model=SARJob, status_code=202)
    def analyse(identifier: str, body: AnalysisRequest):
        return q().enqueue(identifier, body)

    @router.get("/jobs/{identifier}", response_model=SARJob)
    def job(identifier: str):
        return q().view(identifier)

    @router.delete("/jobs/{identifier}", status_code=204)
    def remove_job(identifier: str):
        if q().retained_lease is not None:
            raise WebError(
                409,
                "sar_process_unverified",
                "Verify worker cleanup before removing task records.",
            )
        q().jobs.remove(identifier)
        return Response(status_code=204)

    @router.post("/jobs/{identifier}/cancel", response_model=SARJob)
    def cancel(identifier: str):
        return q().cancel(identifier)

    @router.post("/jobs/{identifier}/resume", response_model=SARJob, status_code=202)
    def resume(identifier: str, body: ResumeRequest):
        return q().resume(identifier, body.expected_input_sha256)

    @router.get("/jobs/{identifier}/pairs", response_model=PairPage)
    def pairs(identifier: str, page: int = 1, page_size: int = 50):
        result = q().jobs.pairs(identifier, page, page_size)
        result.job = q().view(identifier)
        return result

    @router.get("/jobs/{identifier}/export")
    def export(identifier: str, format: str = "csv"):
        if format not in {"csv", "json"}:
            raise WebError(422, "sar_export_format", "Choose CSV or JSON export.")
        q().jobs.pairs(
            identifier, 1, 1
        )  # Refuse partial/foreign/removed results before headers.
        return StreamingResponse(
            export_csv(q(), identifier)
            if format == "csv"
            else export_json(q(), identifier),
            media_type="text/csv; charset=utf-8"
            if format == "csv"
            else "application/json",
            headers={
                "Content-Disposition": f'attachment; filename="SAR-{identifier}.{format}"'
            },
        )

    return router
