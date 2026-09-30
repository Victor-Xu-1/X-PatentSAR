"""Typed local environment management contract, separate from patent results."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictStr, model_validator

from .models import DTO, Error, JobStatus

ComponentId = Literal["installer", "base", "decimer", "decimer-models", "admet", "admet-models"]
ComponentStatus = Literal["unchecked", "checking", "missing", "partial", "ready", "unconfigured", "incompatible", "error"]


class EnvironmentCheck(DTO):
    name: str
    ok: bool
    message: str


class EnvironmentComponent(DTO):
    id: ComponentId
    name: str
    description: str
    version: str
    detected_version: str | None
    status: ComponentStatus
    location: str | None
    kind: Literal["tool", "runtime", "models"]
    group: Literal["tools", "base", "structure", "admet"]
    required: bool
    installable: bool
    download_bytes: int | None = Field(ge=0)
    installed_bytes: int | None = Field(ge=0)
    license: str
    source_url: str
    checks: list[EnvironmentCheck]
    problem: str | None


class EnvironmentSettings(DTO):
    install_root: str
    allowed_root: str
    revision: int = Field(ge=0)
    enabled: bool
    reason: str | None


class EnvironmentSettingsRequest(DTO):
    install_root: StrictStr = Field(min_length=1, max_length=512)
    expected_revision: int = Field(ge=0)


class EnvironmentPreset(DTO):
    id: str
    name: str
    description: str
    component_ids: list[ComponentId]


class EnvironmentOperationRequest(DTO):
    action: Literal["inspect", "install"]
    component_ids: list[ComponentId] = Field(min_length=1, max_length=6)
    request_id: StrictStr = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    expected_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def unique_components(self) -> EnvironmentOperationRequest:
        if len(set(self.component_ids)) != len(self.component_ids):
            raise ValueError("Repeated component IDs are not an installation plan")
        return self


class EnvironmentOperation(DTO):
    id: str
    request_id: str
    action: Literal["inspect", "install"]
    component_ids: list[ComponentId]
    status: JobStatus
    created_at: str
    started_at: str | None
    finished_at: str | None
    install_root: str
    stage: str
    completed_components: list[ComponentId]
    log_tail: list[str]
    error: Error | None
    applied: bool


class EnvironmentCatalog(DTO):
    settings: EnvironmentSettings
    components: list[EnvironmentComponent]
    presets: list[EnvironmentPreset]
    checked_at: str | None
    active_operation: EnvironmentOperation | None
    operations: list[EnvironmentOperation]
