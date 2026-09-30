"""Environment use cases: approved location, persisted plans and verified activation."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .analysis import AnalysisService
from .environment_config import CONFIG_KEYS, EnvironmentConfig
from .environment_models import (
    EnvironmentCatalog,
    EnvironmentComponent,
    EnvironmentOperation,
    EnvironmentOperationRequest,
    EnvironmentPreset,
    EnvironmentSettings,
    EnvironmentSettingsRequest,
)
from .environment_paths import ManagedStorage
from .environment_process import EnvironmentProcessRunner
from .environment_queue import EnvironmentQueue
from .environment_storage import EnvironmentStore
from .errors import WebError
from .files import private_directory
from .processes import ProcessRunner
from .storage import encode


class EnvironmentManager:
    def __init__(
        self,
        state_root: Path,
        analysis: AnalysisService,
        catalog: Callable[[], list[dict[str, Any]]],
        *,
        storage: ManagedStorage | None = None,
        runner: ProcessRunner | None = None,
        config: EnvironmentConfig | None = None,
        recipe_identity: Callable[[], str] | None = None,
    ) -> None:
        self.analysis = analysis
        self.storage = storage or ManagedStorage.from_environment(state_root)
        self.config = config or EnvironmentConfig()
        self.store = EnvironmentStore(state_root, self.storage.default_root)
        self.metadata = catalog
        self.recipe_identity = recipe_identity or (
            lambda: hashlib.sha256(encode(self.metadata()).encode()).hexdigest()
        )
        self.queue = EnvironmentQueue(
            self.store,
            runner or EnvironmentProcessRunner(),
            self.storage.operation_timeout_seconds,
            self._completed,
        )

    def start(self) -> None:
        self.queue.start()

    def close(self) -> None:
        self.queue.close()

    def settings(self) -> EnvironmentSettings:
        saved = self.store.settings()
        reason = self.storage.enabled_reason()
        if self.queue.cleanup_failure:
            reason = self.queue.cleanup_failure.message
        try:
            self.storage.validate(saved["install_root"])
        except WebError as error:
            reason = error.message
        return EnvironmentSettings(
            install_root=saved["install_root"],
            allowed_root=str(self.storage.allowed_root),
            revision=saved["revision"],
            enabled=reason is None,
            reason=reason,
        )

    def save_settings(self, request: EnvironmentSettingsRequest) -> EnvironmentSettings:
        if reason := self.storage.enabled_reason():
            raise WebError(409, "environment_platform", reason)
        root = self.storage.validate(request.install_root)
        self.store.save_settings(root, request.expected_revision)
        return self.settings()

    def _bindings(self) -> dict[str, str | None]:
        return self.config.bindings(self.analysis.settings)

    def _source_key(self) -> str:
        info = {
            "bindings": self._bindings(),
            "config": self.config.fingerprint(),
            "catalog": self.recipe_identity(),
        }
        return hashlib.sha256(encode(info).encode()).hexdigest()

    def catalog(self) -> EnvironmentCatalog:
        reports = self.store.reports(self._source_key())
        components = [
            EnvironmentComponent.model_validate(reports.get(item["id"], item))
            for item in self.metadata()
        ]
        operations = [self.store.operation(row) for row in self.store.history()]
        active = next(
            (
                operation
                for operation in operations
                if operation.status in {"queued", "running"}
            ),
            None,
        )
        saved = self.store.settings()
        return EnvironmentCatalog(
            settings=self.settings(),
            components=components,
            presets=[
                EnvironmentPreset(
                    id="reading",
                    name="先阅读 PDF、查看数据",
                    description="基础 PDF、RapidOCR 与 RDKit 环境；不需要 GPU。",
                    component_ids=["base"],
                ),
                EnvironmentPreset(
                    id="extraction",
                    name="完整专利结构与活性提取",
                    description="基础环境 + DECIMER 识别/分割环境与模型；保持同一正式提取主链。",
                    component_ids=["base", "decimer", "decimer-models"],
                ),
                EnvironmentPreset(
                    id="admet",
                    name="分子属性与 ADMET 分析",
                    description="独立 Python 3.12 CPU 环境与官方校验模型；不启用收费模型。",
                    component_ids=["base", "admet", "admet-models"],
                ),
            ],
            checked_at=saved["checked_at"] if reports else None,
            active_operation=active,
            operations=operations,
        )

    def enqueue(self, request: EnvironmentOperationRequest) -> EnvironmentOperation:
        selected = self.settings()
        if not selected.enabled:
            raise WebError(
                409,
                "environment_disabled",
                selected.reason or "Environment installation is disabled.",
            )
        if not self.queue.thread or not self.queue.thread.is_alive():
            raise WebError(
                503, "environment_queue", "Environment controller is not running."
            )
        ids = set(request.component_ids)
        known = {item["id"]: item for item in self.metadata()}
        if (
            not ids <= set(known)
            or request.action == "install"
            and any(not known[identifier]["installable"] for identifier in ids)
        ):
            raise WebError(
                409,
                "environment_component",
                "Only pinned, supported component recipes may be installed.",
            )
        root = self.storage.validate(selected.install_root)
        if request.action == "install":
            self.storage.prepare(str(root))
        payload = {
            "schema_version": 1,
            "requires_owner_ack": True,
            "action": request.action,
            "component_ids": sorted(ids),
            "install_root": str(root),
            "bindings": self._bindings(),
            "cache_root": str(self.store.root / "downloads"),
            "config_fingerprint": self.config.fingerprint(),
            "source_key": self._source_key(),
        }
        fingerprint = hashlib.sha256(
            encode({**request.model_dump(), "component_ids": sorted(ids)}).encode()
        ).hexdigest()
        operation, created = self.store.enqueue(
            request.request_id, fingerprint, payload, request.expected_revision
        )
        if created:
            private_directory(self.store.root / "downloads")
            self.queue.wake.set()
        return operation

    def operation(self, identifier: str) -> EnvironmentOperation:
        return self.store.operation(self.store.row(identifier))

    def cancel(self, identifier: str) -> EnvironmentOperation:
        operation = self.store.request_cancel(identifier)
        self.queue.wake.set()
        return operation

    def _verified_bindings(
        self, plan: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, str]:
        bindings = result["bindings"]
        if not set(bindings) <= set(CONFIG_KEYS):
            raise WebError(
                409,
                "environment_result",
                "Unexpected environment binding keys were rejected.",
            )
        root = Path(plan["install_root"])
        safe = {}
        reports = {
            item["id"]: EnvironmentComponent.model_validate(item)
            for item in result["components"]
        }
        for identifier, raw in bindings.items():
            if not isinstance(raw, str) or not Path(raw).is_absolute() or "\x00" in raw:
                raise WebError(
                    409, "environment_result", "Environment binding paths are invalid."
                )
            location = Path(raw)
            if (
                reports.get(identifier) is None
                or reports[identifier].status != "ready"
                or reports[identifier].location != raw
            ):
                raise WebError(
                    409,
                    "environment_result",
                    "Only actual verified ready bindings can be activated.",
                )
            if raw != plan["bindings"].get(identifier):
                if not location.is_relative_to(root) or not location.exists():
                    raise WebError(
                        409,
                        "environment_result",
                        "New environment paths must remain within their owned installation prefix.",
                    )
                for parent in (location.parent, *location.parents):
                    if parent.is_relative_to(root) and parent.is_symlink():
                        raise WebError(
                            409,
                            "environment_result",
                            "New environment prefix parents cannot be symbolic links.",
                        )
            safe[identifier] = raw
        return safe

    def _completed(self, plan: dict[str, Any], result: dict[str, Any]) -> None:
        if plan["action"] == "install":
            bindings = self._verified_bindings(plan, result)
            additional = result.get("additional_config") or {}
            if not isinstance(additional, dict):
                raise WebError(
                    409,
                    "environment_result",
                    "Additional environment configuration is invalid.",
                )
            for value in additional.values():
                if not isinstance(value, str) or not Path(value).is_relative_to(
                    Path(plan["install_root"])
                ):
                    raise WebError(
                        409,
                        "environment_result",
                        "Model adapter paths must remain within their owned prefix.",
                    )
            self.analysis.configure(
                lambda: self.config.publish(
                    plan["operation_id"],
                    plan["config_fingerprint"],
                    bindings,
                    additional=additional,
                )
            )
            self.store.update(plan["operation_id"], applied=1)
            effective = self._bindings()
            conflicts = [
                identifier
                for identifier in bindings
                if effective.get(identifier) != bindings[identifier]
            ]
            if conflicts:
                raise WebError(
                    409,
                    "environment_override",
                    "Verified environments were installed, but explicit operator environment variables override the saved paths. Remove those overrides and configure again; no running job was changed.",
                )
        reports = [
            EnvironmentComponent.model_validate(item).model_dump()
            for item in result["components"]
        ]
        self.store.publish_reports(self._source_key(), reports)
