"""Revalidate a private server plan and the persisted process-owner handshake."""

from __future__ import annotations

import os
import re
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patent_sar_extractor.web.environment_models import COMPONENT_IDS, MAX_COMPONENTS

from .environment_files import checked_directory, load_json


@dataclass(frozen=True)
class EnvironmentPlan:
    operation_id: str
    action: str
    component_ids: list[Any]
    install_root: Path
    cache_root: Path
    operation_dir: Path
    bindings: dict[str, str | None]
    requires_owner_ack: bool


def read_plan(path: Path) -> EnvironmentPlan:
    directory = checked_directory(path.parent, private=True)
    if path.name != "environment-plan.json" or path.is_symlink():
        raise ValueError("A private server plan file is required")
    info = path.stat()
    if (
        info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o022
        or info.st_nlink != 1
    ):
        raise ValueError("Plan ownership/permissions differ")
    value = load_json(path)
    required = {
        "schema_version",
        "operation_id",
        "action",
        "component_ids",
        "install_root",
        "bindings",
        "cache_root",
    }
    optional = {"requires_owner_ack", "config_fingerprint", "source_key"}
    if set(value) - required - optional or not required <= set(value):
        raise ValueError("Unknown/missing environment plan fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported environment plan schema")
    identifier = value["operation_id"]
    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise ValueError("Invalid operation identity")
    if directory.name != identifier or value["action"] not in {"inspect", "install"}:
        raise ValueError("Operation directory/action differs")
    ids = value["component_ids"]
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= MAX_COMPONENTS
        or any(not isinstance(x, str) or x not in COMPONENT_IDS for x in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("Component selection left the fixed allowlist")
    bindings = value["bindings"]
    if not isinstance(bindings, dict) or set(bindings) != COMPONENT_IDS:
        raise ValueError("Plan must capture all configured component bindings")
    for raw in bindings.values():
        if raw is not None:
            _path(raw)
    root = _path(value["install_root"])
    # Inspection is read-only and may precede creation of the selected root.
    for parent in (root, *root.parents):
        if parent.is_symlink():
            raise ValueError("Linked installation parent")
    if value["action"] == "install":
        checked_directory(root, private=True)
        marker = load_json(root / ".x-patentsar-environments.json", 4096)
        if marker != {
            "schema_version": 1,
            "product": "X-PatentSAR",
            "uid": os.getuid(),
        }:
            raise ValueError(
                "Installation root is not operator-prepared managed storage"
            )
    cache = checked_directory(_path(value["cache_root"]))
    if (
        root == directory
        or root == cache
        or directory.is_relative_to(root)
        or cache.is_relative_to(root)
    ):
        raise ValueError(
            "Operation/cache directories must be separate from immutable installs"
        )
    if (directory / "environment-result.json").exists():
        raise ValueError("Completed operation directories cannot be replayed")
    ack = value.get("requires_owner_ack", False)
    if type(ack) is not bool:
        raise ValueError("Owner handshake flag must be boolean")
    return EnvironmentPlan(
        identifier, value["action"], ids, root, cache, directory, bindings, ack
    )


def _path(raw: Any) -> Path:
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw) > 4096
        or any(ord(c) < 32 for c in raw)
        or "\\" in raw
        or ":" in raw
        or any(p in {".", ".."} for p in raw.split("/"))
    ):
        raise ValueError("Invalid absolute Linux plan path")
    path = Path(raw)
    if not path.is_absolute() or path == Path("/") or path.is_relative_to("/mnt"):
        raise ValueError("Plan paths must stay on the approved Linux filesystem")
    return path


def wait_for_owner(
    plan: EnvironmentPlan, cancel: threading.Event, *, timeout: float = 10
) -> None:
    if not plan.requires_owner_ack:
        return
    deadline = time.monotonic() + min(timeout, 10)
    marker = plan.operation_dir / "environment-owner.json"
    while not marker.exists():
        if cancel.wait(0.05):
            raise InterruptedError("Owner acknowledgement cancelled")
        if time.monotonic() >= deadline:
            raise TimeoutError("Persisted process owner acknowledgement is missing")
    value = load_json(marker, 4096)
    info = marker.stat()
    fields = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()
    if (
        info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o022
        or value.get("operation_id") != plan.operation_id
        or type(value.get("pid")) is not int
        or value["pid"] != os.getpid()
        or type(value.get("start_ticks")) is not int
        or value["start_ticks"] != int(fields[19])
        or value.get("boot_id")
        != Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    ):
        raise ValueError("Persisted process owner identity differs")
