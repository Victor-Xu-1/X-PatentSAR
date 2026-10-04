"""Environment use cases: approved location, persisted plans and verified activation."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .analysis import AnalysisService
from .environment_catalog import component_view
from .environment_config import CONFIG_KEYS, EnvironmentConfig
from .environment_models import (
    ComponentId,
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
        self.metadata = catalog
        self.store = EnvironmentStore(
            state_root, self.storage.default_root, self.resolve_components
        )
        self.recipe_identity = recipe_identity or (
            lambda: hashlib.sha256(encode(self.metadata()).encode()).hexdigest()
        )
        self.queue = EnvironmentQueue(
            self.store,
            runner or EnvironmentProcessRunner(),
            self.storage.operation_timeout_seconds,
            self._completed,
            self._prepare,
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

    def _source_key(
        self,
        bindings: dict[str, str | None] | None = None,
        fingerprint: str | None = None,
    ) -> str:
        info = {
            "bindings": self._bindings() if bindings is None else bindings,
            "config": self.config.fingerprint() if fingerprint is None else fingerprint,
            "catalog": self.recipe_identity(),
        }
        return hashlib.sha256(encode(info).encode()).hexdigest()

    def _snapshot(self) -> tuple[dict[str, str | None], str, str]:
        before = self.config.fingerprint()
        bindings = self._bindings()
        after = self.config.fingerprint()
        if before != after:
            raise WebError(
                409,
                "environment_configuration_changed",
                "Runtime configuration changed while reading; refresh before checking environments.",
            )
        return bindings, after, self._source_key(bindings, after)

    def catalog(self) -> EnvironmentCatalog:
        bindings, _, source_key = self._snapshot()
        records = self.store.report_records()
        components = [
            component_view(
                item, bindings.get(item["id"]), source_key, records.get(item["id"])
            )
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
                    name="PDF 提取与六项指标",
                    description="PDF/OCR、DECIMER 与 ADMET CPU 环境和模型；支持一次完成默认任务。",
                    component_ids=[
                        "base",
                        "decimer",
                        "decimer-models",
                        "admet",
                        "admet-models",
                    ],
                ),
                EnvironmentPreset(
                    id="admet",
                    name="分子属性与 ADMET 分析",
                    description="独立 Python 3.12 CPU 环境与官方校验模型；不启用收费模型。",
                    component_ids=["base", "admet", "admet-models"],
                ),
            ],
            checked_at=saved["checked_at"],
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
        bindings, fingerprint, source_key = self._snapshot()
        payload = {
            "schema_version": 1,
            "requires_owner_ack": True,
            "action": request.action,
            "component_ids": self.resolve_components(sorted(ids))
            if request.action == "install"
            else sorted(ids),
            "install_root": str(root),
            "bindings": bindings,
            "cache_root": str(self.store.root / "downloads"),
            "config_fingerprint": fingerprint,
            "source_key": source_key,
        }
        fingerprint = hashlib.sha256(
            encode({**request.model_dump(), "component_ids": sorted(ids)}).encode()
        ).hexdigest()
        operation, created = self.store.enqueue(
            request.request_id, fingerprint, payload, request.expected_revision
        )
        if created:
            self.queue.wake.set()
        return operation

    def resolve_components(self, identifiers: list[ComponentId]) -> list[ComponentId]:
        known = {item["id"]: item for item in self.metadata()}
        visiting: set[str] = set()
        result: list[ComponentId] = []

        def visit(identifier: ComponentId) -> None:
            if identifier not in known or identifier in visiting:
                raise WebError(
                    409,
                    "environment_dependencies",
                    "Component dependencies are unknown or cyclic; installation was not started.",
                )
            if identifier in result:
                return
            visiting.add(identifier)
            for dependency in known[identifier].get("dependencies", []):
                visit(dependency)
            visiting.remove(identifier)
            result.append(identifier)

        for identifier in identifiers:
            visit(identifier)
        if len(result) > 6:
            raise WebError(
                409,
                "environment_dependencies",
                "The component dependency plan exceeded its fixed bound.",
            )
        return result

    def operation(self, identifier: str) -> EnvironmentOperation:
        return self.store.operation(self.store.row(identifier))

    def _prepare(self, plan: dict[str, Any]) -> None:
        root = self.storage.validate(plan["install_root"])
        if plan["cache_root"] != str(self.store.root / "downloads"):
            raise WebError(
                409,
                "environment_record",
                "Environment cache must belong to its private controller.",
            )
        if plan["action"] == "install":
            self.storage.prepare(str(root))
        private_directory(self.store.root / "downloads")

    def cancel(self, identifier: str) -> EnvironmentOperation:
        operation = self.store.request_cancel(identifier)
        self.queue.wake.set()
        return operation

    def _verified_bindings(
        self, plan: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, str]:
        bindings = result["bindings"]
        if not set(bindings) <= set(CONFIG_KEYS) or not set(
            plan["component_ids"]
        ) <= set(bindings):
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
                not location.exists()
                or identifier in {"installer", "base", "decimer", "admet"}
                and not os.access(location, os.X_OK)
            ):
                raise WebError(
                    409,
                    "environment_result",
                    "Verified environment paths became unavailable before activation.",
                )
            if (
                reports.get(identifier) is None
                or reports[identifier].status != "ready"
                or reports[identifier].location != raw
                or not reports[identifier].detected_version
                or not any(check.ok for check in reports[identifier].checks)
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
        if plan["action"] == "inspect" and self._snapshot()[2] != plan["source_key"]:
            raise WebError(
                409,
                "environment_inspection_changed",
                "Runtime configuration or recipes changed during inspection; historical results were preserved but not published as current. Refresh and inspect again.",
            )
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
                if not isinstance(value, str):
                    raise WebError(
                        409,
                        "environment_result",
                        "Model adapter paths must remain within their owned prefix.",
                    )
                location = Path(value)
                owned = location.is_relative_to(Path(plan["install_root"]))
                legacy = (
                    Path(bindings["decimer"]).parent.parent
                    / "lib/python3.10/site-packages/decimer_segmentation/mask_rcnn_molecule.h5"
                    if "decimer" in bindings
                    else None
                )
                if not owned and location != legacy:
                    raise WebError(
                        409,
                        "environment_result",
                        "Only the selected verified runtime's original segmentation cache may be reused read-only.",
                    )
                from patent_sar_extractor.workers.environment_files import file_sha256
                from patent_sar_extractor.workers.environment_segmentation import (
                    SEGMENTATION_SHA256,
                )

                if (
                    any(path.is_symlink() for path in (location, *location.parents))
                    or file_sha256(location) != SEGMENTATION_SHA256
                ):
                    raise WebError(
                        409,
                        "environment_result",
                        "Segmentation content changed before activation; no model path was published.",
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
        source_key = (
            plan["source_key"] if plan["action"] == "inspect" else self._snapshot()[2]
        )
        self.store.publish_reports(source_key, reports)
