"""Bounded, cheap environment projection; file presence is not SDK verification."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .environment_models import EnvironmentComponent, EnvironmentLastCheck
from .errors import WebError

_REPORT_FIELDS = {
    "status",
    "detected_version",
    "checks",
    "installed_bytes",
    "problem",
    "checked_at",
}


def _presence(
    component: EnvironmentComponent, location: str | None
) -> tuple[str, str, str | None]:
    if location is None:
        return "unconfigured", "unconfigured", "未配置该组件路径。"
    if (
        not location
        or len(location) > 4096
        or not Path(location).is_absolute()
        or any(ord(c) < 32 for c in location)
        or "\\" in location
    ):
        return "unknown", "error", "配置路径无效；未运行检测或修改文件。"
    try:
        mode = Path(location).stat().st_mode
        valid = stat.S_ISDIR(mode) if component.kind == "models" else stat.S_ISREG(mode)
        if not valid or component.kind != "models" and not os.access(location, os.X_OK):
            return "unknown", "error", "配置路径的类型或访问权限不符合要求。"
    except FileNotFoundError:
        return "missing", "missing", "配置路径不存在。"
    except OSError:
        return "unknown", "error", "无法读取配置路径；未运行检测或修改文件。"
    return "present", "unchecked", None


def component_view(
    metadata: dict[str, Any],
    location: str | None,
    source_key: str,
    record: dict[str, Any] | None,
) -> EnvironmentComponent:
    """Current cache, same-path history and lightweight presence have one owner."""
    component = EnvironmentComponent.model_validate(metadata)
    presence, status, problem = _presence(component, location)
    values: dict[str, Any] = {
        **metadata,
        "location": location,
        "presence": presence,
        "status": status,
        "problem": problem,
        "verification": "unchecked",
        "detected_version": None,
        "checks": [],
        "installed_bytes": None,
        "checked_at": None,
        "last_check": None,
    }
    if record is not None:
        try:
            saved = EnvironmentComponent.model_validate(record["report"])
        except (ValidationError, KeyError, TypeError) as error:
            raise WebError(
                409,
                "environment_record",
                "Saved environment checks are invalid; no files were modified.",
            ) from error
        # A new binding cannot borrow checks, observed versions or dates from an old path.
        same_path = saved.id == component.id and saved.location == location
        current = (
            same_path and record["source_key"] == source_key and presence != "unknown"
        )
        if saved.status == "ready" and presence != "present":
            current = False
        if current:
            values.update({key: getattr(saved, key) for key in _REPORT_FIELDS})
            values["verification"] = "current"
            if saved.status == "ready" and (
                not saved.detected_version
                or not saved.checks
                or not all(c.ok for c in saved.checks)
            ):
                values.update(
                    status="error",
                    problem="保存的就绪记录缺少完整检测依据；请重新检测。",
                )
        elif same_path:
            values["verification"] = "stale"
            values["last_check"] = EnvironmentLastCheck(
                status=saved.status,
                detected_version=saved.detected_version,
                checked_at=saved.checked_at,
                checks=saved.checks,
                problem=saved.problem,
            )
    return EnvironmentComponent.model_validate(values)
