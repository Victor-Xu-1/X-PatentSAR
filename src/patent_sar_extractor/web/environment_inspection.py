"""Actual offline component inspection over a captured server binding snapshot."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patent_sar_extractor.workers.admet_models import existing_bundle
from patent_sar_extractor.workers.environment_files import (
    checked_directory,
    file_sha256,
)

from .analysis_process import BoundedAnalysisRunner
from .analysis_runtime import AnalysisSettings, child_environment
from .environment_models import (
    ComponentId,
    ComponentStatus,
    EnvironmentCheck,
    EnvironmentComponent,
)
from .environment_specs import UV_BINARY_SHA256, component_spec, recipe_path
from .errors import WebError

_PROBE = Path(__file__).resolve().parents[1] / "workers/environment_probe_worker.py"


def _checks(result: Mapping[str, object]) -> list[EnvironmentCheck]:
    raw = result.get("checks")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 64:
        raise ValueError("Probe checks are missing/unbounded")
    output = []
    for item in raw:
        if not isinstance(item, dict) or type(item.get("ok")) is not bool:
            raise ValueError("Probe check boolean differs")
        if not isinstance(item.get("name"), str) or not isinstance(
            item.get("message"), str
        ):
            raise TypeError("Probe check text differs")
        if len(item["name"]) > 128 or len(item["message"]) > 1024:
            raise ValueError("Probe check text is unbounded")
        output.append(EnvironmentCheck.model_validate(item))
    return output


@dataclass(frozen=True)
class InspectionContext:
    installer: Path | None = None
    base: Path | None = None
    decimer: Path | None = None
    decimer_models: Path | None = None
    admet: Path | None = None
    admet_models: Path | None = None

    @classmethod
    def from_bindings(cls, bindings: Mapping[str, str | None]) -> InspectionContext:
        allowed = {
            "installer",
            "base",
            "decimer",
            "decimer-models",
            "admet",
            "admet-models",
        }
        if set(bindings) - allowed:
            raise ValueError("Unknown environment binding")
        values = {}
        for key in allowed:
            value = bindings.get(key)
            if value is not None:
                if (
                    not isinstance(value, str)
                    or not value
                    or not Path(value).is_absolute()
                    or "\x00" in value
                    or "\\" in value
                ):
                    raise ValueError("Invalid captured environment path")
                values[key.replace("-", "_")] = Path(value)
        return cls(**values)

    def bindings(self) -> dict[str, str | None]:
        return {
            name: str(value) if value else None
            for name, value in (
                ("installer", self.installer),
                ("base", self.base),
                ("decimer", self.decimer),
                ("decimer-models", self.decimer_models),
                ("admet", self.admet),
                ("admet-models", self.admet_models),
            )
        }


def inspect_components(
    component_ids: list[ComponentId],
    context: InspectionContext,
    *,
    op_dir: Path,
    cancel: threading.Event | None = None,
) -> list[EnvironmentComponent]:
    """Returns exact public DTOs; missing/incompatible components are not hidden.

    Call as an owned durable operation, not a blocking GET health handler. Heavy
    probes share the existing bounded runner; inspection never installs anything.
    """
    if len(component_ids) > 6 or len(set(component_ids)) != len(component_ids):
        raise ValueError("Invalid inspection component set")
    checked_directory(op_dir, private=True)
    runner = BoundedAnalysisRunner()
    bindings = context.bindings()
    results: dict[str, dict[str, Any]] = {}

    def run(
        role: str, python: Path, *, model_name: str | None = None
    ) -> dict[str, Any]:
        key = role + (model_name or "")
        if key not in results:
            payload: dict[str, object] = {"role": role}
            if role == "base":
                payload["base_recipe"] = str(recipe_path("base-runtime.json"))
            if role in {"decimer-ocsrc", "decimer-segmentation"}:
                payload.update(
                    model_root=str(context.decimer_models),
                    recipe=str(recipe_path("decimer-models.json")),
                )
                if model_name:
                    payload["model_name"] = model_name
            env = child_environment(
                AnalysisSettings(pystow_home=context.decimer_models), python, op_dir
            )
            results[key] = runner.run(
                [str(python), "-I", str(_PROBE)],
                payload,
                cwd=op_dir,
                env=env,
                timeout=180,
                cancel=cancel,
            )
        return results[key]

    output = []
    result: dict[str, Any]
    try:
        for component_id in component_ids:
            if cancel is not None and cancel.is_set():
                raise WebError(
                    503,
                    "environment_cancelled",
                    "Environment inspection was cancelled.",
                )
            spec = component_spec(component_id)
            location = bindings[component_id]
            checks: list[EnvironmentCheck] = []
            status: ComponentStatus = "unconfigured" if location is None else "missing"
            problem: str | None = (
                "未配置该组件路径。" if location is None else "配置路径不存在。"
            )
            detected: str | None = None
            size: int | None = None
            if location and Path(location).exists():
                try:
                    path = Path(location)
                    if component_id == "installer":
                        valid = (
                            file_sha256(path, limit=128 * 1024 * 1024)
                            == UV_BINARY_SHA256
                        )
                        checks.append(
                            EnvironmentCheck(
                                name="official_binary",
                                ok=valid,
                                message="Owned uv 0.11.31 official binary SHA-256",
                            )
                        )
                        if valid:
                            result = runner.run(
                                [sys.executable, "-I", str(_PROBE)],
                                {"role": "installer", "uv_path": str(path)},
                                cwd=op_dir,
                                env=child_environment(
                                    AnalysisSettings(), Path(sys.executable), op_dir
                                ),
                                timeout=10,
                                cancel=cancel,
                            )
                            checks.extend(_checks(result))
                        detected = "0.11.31" if valid else None
                    elif component_id in {"base", "admet", "decimer"}:
                        if not path.is_file() or not os.access(path, os.X_OK):
                            raise ValueError("Interpreter is not executable")
                        result = run(component_id, path)
                        checks = _checks(result)
                        detected = str(
                            result.get("versions", {}).get(
                                "DECIMER" if component_id == "decimer" else "admet-ai",
                                result["python"],
                            )
                        )
                    elif component_id == "decimer-models":
                        if context.decimer is None:
                            raise ValueError(
                                "DECIMER runtime must be checked before model load"
                            )
                        for model_name in ("DECIMER_model", "DECIMER_HandDrawn_model"):
                            result = run(
                                "decimer-ocsrc", context.decimer, model_name=model_name
                            )
                            checks.extend(_checks(result))
                        result = run("decimer-segmentation", context.decimer)
                        checks.extend(_checks(result))
                        detected = "OCSR V2 + segmentation 1.5.0"
                    else:
                        manifest = existing_bundle(path)
                        checks.append(
                            EnvironmentCheck(
                                name="model_fingerprint",
                                ok=True,
                                message=f"10 official models: {manifest['model_sha256']}",
                            )
                        )
                        if context.admet is None:
                            raise ValueError(
                                "ADMET runtime is required for a loaded-model check"
                            )
                        # Actual model load is offline in the external interpreter.
                        result = runner.run(
                            [str(context.admet), "-I", str(_PROBE)],
                            {"role": "admet-models", "model_root": str(path)},
                            cwd=op_dir,
                            env=child_environment(
                                AnalysisSettings(), context.admet, op_dir
                            ),
                            timeout=180,
                            cancel=cancel,
                        )
                        checks.extend(_checks(result))
                        detected = "2.0.1"
                        size = sum(entry["size"] for entry in manifest["files"])
                    ready = bool(checks) and all(c.ok for c in checks)
                    status = "ready" if ready else "incompatible"
                    problem = None if ready else "实际版本、CPU 或模型检查未通过。"
                except WebError as exc:
                    if exc.code in {"analysis_cancelled", "environment_cancelled"}:
                        raise
                    status, problem = (
                        "error",
                        "组件检查失败；未下载、修改或降级现有环境。",
                    )
                    checks.append(
                        EnvironmentCheck(name="probe", ok=False, message=exc.code)
                    )
                except (ValueError, OSError, KeyError, TypeError):
                    status, problem = (
                        "partial",
                        "组件内容缺失、不兼容或未通过真实检查；现有文件已保留。",
                    )
                    checks.append(
                        EnvironmentCheck(
                            name="content",
                            ok=False,
                            message="Missing/unsafe/incompatible component content",
                        )
                    )
            installable = (
                spec.requirements is None or recipe_path(spec.requirements).is_file()
            )
            output.append(
                EnvironmentComponent(
                    id=spec.id,
                    name=spec.name,
                    description=spec.description,
                    version=spec.version,
                    detected_version=detected,
                    status=status,
                    location=location,
                    kind=spec.kind,
                    group=spec.group,
                    required=spec.required,
                    installable=installable,
                    download_bytes=spec.download_bytes,
                    installed_bytes=size,
                    license=spec.license,
                    source_url=spec.source_url,
                    checks=checks,
                    problem=problem,
                )
            )
        return output
    finally:
        runner.close()
