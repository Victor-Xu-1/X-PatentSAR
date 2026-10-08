"""Thin adapters for the durable extraction queue."""

from __future__ import annotations

from fastapi import APIRouter

from .jobs import JobQueue
from .llm_job_recovery import renew_job_authorization
from .llm_models import LLMReauthorizeRequest
from .llm_settings import LLMSettingsService
from .models import Job, JobRequest
from .service import WorkspaceService


def job_routes(
    service: WorkspaceService, queue: JobQueue, llm_settings: LLMSettingsService
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.post("/projects/{project_id}/jobs", status_code=202, response_model=Job)
    def start_job(project_id: str, body: JobRequest) -> Job:
        return queue.enqueue(project_id, body)

    @router.get("/jobs")
    def jobs(project_id: str | None = None) -> dict[str, list[Job]]:
        return {
            "items": [service.job(job_id) for job_id in service.job_ids(project_id)]
        }

    @router.get("/jobs/{job_id}", response_model=Job)
    def job(job_id: str) -> Job:
        return service.job(job_id)

    @router.post("/jobs/{job_id}/cancel", response_model=Job)
    def cancel(job_id: str) -> Job:
        return queue.cancel(job_id)

    @router.post("/jobs/{job_id}/llm-authorization", response_model=Job)
    def reauthorize(job_id: str, body: LLMReauthorizeRequest) -> Job:
        return renew_job_authorization(service, llm_settings, job_id, body)

    return router
