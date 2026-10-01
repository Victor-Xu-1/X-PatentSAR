"""Thin project, PDF, result, review, and export HTTP adapters."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response, StreamingResponse

from .errors import WebError
from .exports import export_csv, export_json, selected
from .files import SafeFiles
from .models import (
    Compound,
    ExportRequest,
    Page,
    Project,
    Results,
    Review,
    ReviewRequest,
)
from .molecule_drawing import draw_smiles
from .pdf import crop_image, filename_title, page_info, render_page, stream_upload
from .reviews import put_review
from .service import WorkspaceService
from .task_inputs import patent_identifier


def project_routes(service: WorkspaceService, max_upload_bytes: int) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    uploads = asyncio.Semaphore(2)

    @router.get("/projects")
    def projects() -> dict[str, list[Project]]:
        return {
            "items": [
                service.project(project_id) for project_id in service.project_ids()
            ]
        }

    @router.post("/projects", status_code=201, response_model=Project)
    async def create_project(
        request: Request,
        filename: str,
        title: str | None = None,
        patent_id: str | None = None,
    ) -> Project:
        filename_title(filename)
        if title is not None:
            service._title(title)
        if patent_id:
            patent_id = patent_identifier(patent_id)
        async with uploads:
            uploaded = await stream_upload(
                request, service.store.root / "uploads", max_bytes=max_upload_bytes
            )
            return await run_in_threadpool(
                service.add_pdf, uploaded, filename, title, patent_id
            )

    @router.get("/projects/{project_id}", response_model=Project)
    def project(project_id: str) -> Project:
        return service.project(project_id)

    @router.post("/projects/{project_id}/pdf", response_model=Project)
    async def attach_pdf(project_id: str, request: Request, filename: str) -> Project:
        filename_title(filename)
        service.store.project(project_id)
        async with uploads:
            uploaded = await stream_upload(
                request, service.store.root / "uploads", max_bytes=max_upload_bytes
            )
            return await run_in_threadpool(service.attach_pdf, project_id, uploaded)

    @router.get("/projects/{project_id}/pages/{page}", response_model=Page)
    def pdf_page(project_id: str, page: int) -> Page:
        row = service.store.project(project_id)
        historical_text = ""
        if row["run_root"]:
            ocr = (
                SafeFiles(Path(row["run_root"])).json(
                    "page_classification/page_ocr_cache.json"
                )
                or {}
            )
            page_texts = ocr.get("page_texts", {}) if isinstance(ocr, dict) else {}
            historical_text = (
                page_texts.get(str(page - 1), "")
                if isinstance(page_texts, dict)
                else ""
            )
            if not isinstance(historical_text, str) or len(historical_text) > 200000:
                raise WebError(
                    422, "invalid_ocr", "Page OCR text is invalid or exceeds its limit."
                )
        return page_info(
            service.store.root,
            row,
            page,
            service.result_rows(project_id),
            historical_text=historical_text,
        )

    @router.get("/projects/{project_id}/pages/{page}/image")
    def pdf_image(project_id: str, page: int, scale: float = 1.5) -> Response:
        return Response(
            render_page(
                service.store.root, service.store.project(project_id), page, scale
            ),
            media_type="image/png",
        )

    @router.get("/projects/{project_id}/structures/{compound_id}/image")
    def structure_image(project_id: str, compound_id: str) -> Response:
        row = service.store.compound(project_id, compound_id)
        project = service.store.project(project_id)
        dto = Compound.model_validate_json(row["payload"])
        if row["image_path"] and project["run_root"]:
            data = crop_image(Path(project["run_root"]), row["image_path"])
        elif dto.source.page and dto.source.bbox and project["pdf_rel"]:
            data = render_page(
                service.store.root,
                project,
                dto.source.page,
                1.5,
                bbox=dto.source.bbox,
                geometry_space=row["geometry_space"],
            )
        else:
            raise WebError(
                404, "crop_unavailable", "No safe structure crop is available."
            )
        return Response(data, media_type="image/png")

    @router.get("/projects/{project_id}/structures/{compound_id}/redraw")
    def structure_redraw(
        project_id: str, compound_id: str, fingerprint: str | None = None
    ) -> Response:
        row = service.store.compound(project_id, compound_id)
        dto = Compound.model_validate_json(row["payload"])
        if not dto.smiles:
            raise WebError(
                404,
                "smiles_unavailable",
                "No recorded SMILES is available for a derived drawing.",
            )
        if (
            fingerprint is not None
            and fingerprint != hashlib.sha256(dto.smiles.encode()).hexdigest()
        ):
            raise WebError(
                409,
                "molecule_changed",
                "Recorded molecule changed; refresh the result view.",
            )
        return Response(
            draw_smiles(dto.smiles),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/projects/{project_id}/results", response_model=Results)
    def results(
        project_id: str,
        q: str = "",
        confidence: str = "",
        review: str = "",
        target: str = "",
        page: int = 1,
        page_size: int = 10,
    ) -> Results:
        return service.results(
            project_id,
            q=q,
            confidence=confidence,
            review=review,
            target=target,
            page=page,
            page_size=page_size,
        )

    @router.put("/projects/{project_id}/reviews/{compound_id}", response_model=Review)
    def review(project_id: str, compound_id: str, body: ReviewRequest) -> Review:
        return put_review(service.store, project_id, compound_id, body)

    @router.post("/projects/{project_id}/export")
    def export(
        project_id: str,
        body: ExportRequest,
        q: str = "",
        confidence: str = "",
        review: str = "",
        target: str = "",
    ) -> StreamingResponse:
        project = service.project(project_id)
        rows = selected(
            service.compounds(
                project_id, q=q, confidence=confidence, review=review, target=target
            ),
            body,
        )
        iterator = (
            export_csv(project, rows)
            if body.format == "csv"
            else export_json(project, rows)
        )
        return StreamingResponse(
            iterator,
            media_type="text/csv; charset=utf-8"
            if body.format == "csv"
            else "application/json",
            headers={
                "Content-Disposition": f'attachment; filename="x-patentsar-{project_id}.{body.format}"'
            },
        )

    return router
