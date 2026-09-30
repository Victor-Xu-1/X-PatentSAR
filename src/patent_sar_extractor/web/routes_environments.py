"""Environment routes reuse the same authenticated loopback/session/CSRF boundary."""

from __future__ import annotations

from fastapi import APIRouter

from .environment_models import (
    EnvironmentCatalog,
    EnvironmentOperation,
    EnvironmentOperationRequest,
    EnvironmentSettings,
    EnvironmentSettingsRequest,
)
from .environments import EnvironmentManager


def environment_routes(manager: EnvironmentManager) -> APIRouter:
    router = APIRouter(prefix="/api/v1/environments")

    @router.get("", response_model=EnvironmentCatalog)
    def catalog() -> EnvironmentCatalog:
        return manager.catalog()

    @router.put("/settings", response_model=EnvironmentSettings)
    def settings(body: EnvironmentSettingsRequest) -> EnvironmentSettings:
        return manager.save_settings(body)

    @router.post("/operations", response_model=EnvironmentOperation, status_code=202)
    def operation(body: EnvironmentOperationRequest) -> EnvironmentOperation:
        return manager.enqueue(body)

    @router.get("/operations/{identifier}", response_model=EnvironmentOperation)
    def operation_status(identifier: str) -> EnvironmentOperation:
        return manager.operation(identifier)

    @router.post("/operations/{identifier}/cancel", response_model=EnvironmentOperation)
    def cancel(identifier: str) -> EnvironmentOperation:
        return manager.cancel(identifier)

    return router
