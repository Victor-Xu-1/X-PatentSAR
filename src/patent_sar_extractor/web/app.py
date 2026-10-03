"""Factory for the authenticated local API and optional built SPA."""

from __future__ import annotations

import logging
import math
import os
import sys
from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response

from patent_sar_extractor.contracts import (
    WEB_API_SCHEMA,
    WEB_API_SCHEMA_VERSION,
    product_ref,
    ruleset_ref,
    schema_ref,
)

from .analysis import AnalysisService
from .analysis_process import BoundedAnalysisRunner
from .analysis_runtime import AnalysisSettings
from .environment_paths import ManagedStorage
from .environments import EnvironmentManager
from .errors import WebError
from .jobs import JobQueue
from .owner import WorkspaceOwner
from .processes import CLIProcessRunner, ProcessRunner
from .routes_analysis import analysis_routes
from .routes_environments import environment_routes
from .routes_jobs import job_routes
from .routes_projects import project_routes
from .security import SecurityMiddleware, Sessions, loopback_host
from .service import WorkspaceService
from .static_files import serve_frontend, ui_ready

logger = logging.getLogger(__name__)


def create_app(
    state_root: str | Path,
    frontend_dir: str | Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    import_runs: Sequence[str | Path] = (),
    runner: ProcessRunner | None = None,
    job_timeout_seconds: float = 86400,
    max_upload_bytes: int = 128 * 1024 * 1024,
    body_timeout_seconds: float = 120,
    body_idle_seconds: float = 15,
    analysis_settings: AnalysisSettings | None = None,
    analysis_runner: BoundedAnalysisRunner | None = None,
    environment_storage: ManagedStorage | None = None,
    environment_runner: ProcessRunner | None = None,
    environment_catalog: Callable[[], list[dict[str, object]]] | None = None,
) -> FastAPI:
    """API-only with frontend_dir=None. Caller chooses the private state root.

    The lifespan owns the workspace lock, recovery and single consumer. Use a
    context-managed TestClient or an ASGI server with lifespan enabled.
    """
    loopback_host(host)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise WebError(400, "invalid_port", "Port must be between 1 and 65535.")
    if (
        not math.isfinite(job_timeout_seconds)
        or not 0.05 <= job_timeout_seconds <= 86400
    ):
        raise WebError(
            400,
            "invalid_timeout",
            "Job lifetime must be bounded between 0.05 seconds and 24 hours.",
        )
    if not 1 <= max_upload_bytes <= 128 * 1024 * 1024:
        raise WebError(
            400,
            "invalid_upload_limit",
            "Upload limit must be between 1 byte and 128 MiB.",
        )
    if (
        not 0.01 <= body_timeout_seconds <= 120
        or not 0.01 <= body_idle_seconds <= body_timeout_seconds
    ):
        raise WebError(
            400,
            "invalid_timeout",
            "Body receive timeouts must be bounded by 120 seconds.",
        )
    service = WorkspaceService(state_root)
    analysis = AnalysisService(
        service.store.root, service, settings=analysis_settings, runner=analysis_runner
    )
    queue = JobQueue(service, runner or CLIProcessRunner(), job_timeout_seconds)
    service.corrections.on_save = queue.corrected
    recipe_identity = None
    if environment_catalog is None:
        from .environment_specs import catalog_fingerprint, component_catalog

        environment_catalog = component_catalog
        recipe_identity = catalog_fingerprint
    environments = EnvironmentManager(
        service.store.root,
        analysis,
        environment_catalog,
        storage=environment_storage,
        runner=environment_runner,
        recipe_identity=recipe_identity,
    )
    owner = WorkspaceOwner(service.store.root)
    frontend = Path(frontend_dir) if frontend_dir is not None else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owner.acquire()
        started = False
        try:
            for directory in import_runs:
                service.import_run(directory)
            queue.start()
            started = True
            environments.start()
            app.state.ready = True
            yield
        finally:
            app.state.ready = False
            failures: list[Exception] = []
            try:
                environments.close()
            except Exception as error:
                logger.exception(
                    "Environment cleanup failed (%s)", type(error).__name__
                )
                failures.append(error)
            try:
                analysis.close()
            except Exception as error:
                logger.exception("Analysis cleanup failed (%s)", type(error).__name__)
                failures.append(error)
            if started:
                try:
                    queue.close()
                except Exception as error:
                    logger.exception("Queue cleanup failed (%s)", type(error).__name__)
                    failures.append(error)
            if failures:
                # Do not allow recovery by another server while an owned worker's
                # shutdown remains unverified. Process exit releases the lock.
                raise ExceptionGroup("Workspace shutdown was not verified", failures)
            owner.release()

    app = FastAPI(
        title="X-PatentSAR local Web API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.workspace = service
    app.state.queue = queue
    app.state.analysis = analysis
    app.state.environments = environments
    app.state.owner = owner
    app.state.ready = False
    app.add_middleware(
        SecurityMiddleware,
        store=service.store,
        host=host,
        port=port,
        max_upload_bytes=max_upload_bytes,
        body_timeout_seconds=body_timeout_seconds,
        body_idle_seconds=body_idle_seconds,
    )

    @app.exception_handler(WebError)
    async def web_error(request: Request, error: WebError) -> JSONResponse:
        return JSONResponse(error.payload(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            WebError(
                422,
                "invalid_request",
                "Request fields are missing, invalid, or unsupported.",
            ).payload(),
            status_code=422,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse(
            WebError(
                error.status_code,
                "endpoint_not_found" if error.status_code == 404 else "http_error",
                "API endpoint does not exist."
                if error.status_code == 404
                else "Request could not be processed.",
            ).payload(),
            status_code=error.status_code,
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        logger.error("HTTP boundary failed (%s)", type(error).__name__)
        return JSONResponse(
            WebError(
                500, "internal_error", "Local server could not complete the request."
            ).payload(),
            status_code=500,
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, object]:
        return {
            "product": product_ref(),
            "schema": schema_ref(WEB_API_SCHEMA, WEB_API_SCHEMA_VERSION),
            "ruleset": ruleset_ref(),
            "ready": app.state.ready
            and bool(queue.thread and queue.thread.is_alive())
            and (frontend is None or ui_ready(frontend)),
            "capabilities": analysis.capabilities(),
        }

    @app.get("/api/v1/session")
    def session(request: Request) -> JSONResponse:
        return Sessions(service.store).bootstrap(request)

    @app.get("/api/v1/runtime")
    def runtime() -> dict[str, object]:
        from patent_sar_extractor.core.env_runner import get_python

        interpreters = [
            {
                "role": "base",
                "configured": True,
                "available": os.access(sys.executable, os.X_OK),
            }
        ]
        for role in ("decimer", "smiles_engine", "paddleocr"):
            value = get_python(role)
            interpreters.append(
                {
                    "role": role,
                    "configured": bool(value),
                    "available": bool(
                        value and Path(value).is_file() and os.access(value, os.X_OK)
                    ),
                }
            )
        admet_python = analysis.settings.admet_python
        interpreters.append(
            {
                "role": "admet",
                "configured": admet_python is not None,
                "available": bool(
                    admet_python
                    and admet_python.is_file()
                    and os.access(admet_python, os.X_OK)
                ),
            }
        )
        return {
            "product": product_ref(),
            "storage": {
                "state_root": str(service.store.root),
                "platform": sys.platform,
            },
            "interpreters": interpreters,
            "capabilities": analysis.capabilities(),
        }

    app.include_router(project_routes(service, max_upload_bytes))
    app.include_router(job_routes(service, queue))
    app.include_router(analysis_routes(service, analysis))
    app.include_router(environment_routes(environments))

    @app.get("/{path:path}")
    def frontend_route(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise WebError(404, "endpoint_not_found", "API endpoint does not exist.")
        if frontend is None:
            raise WebError(
                503,
                "ui_not_built",
                "API-only mode: no built frontend directory was provided.",
            )
        return serve_frontend(frontend, path)

    return app
