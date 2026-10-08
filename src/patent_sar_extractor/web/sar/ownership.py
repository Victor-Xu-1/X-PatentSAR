"""Durable SAR worker identity; recovery never signals a reused/unknown PID."""

from __future__ import annotations

from pathlib import Path

from ..analysis_children import Child, read_child
from ..errors import WebError
from ..files import SafeFiles
from ..process_identity import previous_kernel_boot, process_present, valid_boot_id
from .assets import atomic_json


def boot_id() -> str:
    value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if not valid_boot_id(value):
        raise WebError(
            503,
            "sar_process_unverified",
            "Current worker kernel identity is unavailable.",
        )
    return value


def intent(root: Path, job_id: str, input_sha256: str, attempt: str) -> None:
    atomic_json(
        root,
        f"launch-{attempt}.json",
        {
            "schema": 1,
            "job_id": job_id,
            "input_sha256": input_sha256,
            "boot_id": boot_id(),
        },
    )


def started(
    root: Path, job_id: str, input_sha256: str, attempt: str, child: Child
) -> None:
    current = read_child(child.pid)
    if current is None or current.start_ticks != child.start_ticks:
        raise WebError(
            503, "sar_process_unverified", "SAR worker ownership could not be saved."
        )
    atomic_json(
        root,
        f"process-{attempt}.json",
        {
            "schema": 1,
            "job_id": job_id,
            "input_sha256": input_sha256,
            "boot_id": boot_id(),
            "pid": child.pid,
            "start_ticks": child.start_ticks,
        },
    )


def absent(files: SafeFiles, job_id: str, input_sha256: str, attempt: str) -> bool:
    clean = files.json(f"cleanup-{attempt}.json")
    if clean == {
        "schema": 1,
        "job_id": job_id,
        "input_sha256": input_sha256,
        "verified": True,
    }:
        return True
    launch = files.json(f"launch-{attempt}.json")
    if (
        not isinstance(launch, dict)
        or set(launch) != {"schema", "job_id", "input_sha256", "boot_id"}
        or launch.get("schema") != 1
        or launch.get("job_id") != job_id
        or launch.get("input_sha256") != input_sha256
        or not valid_boot_id(launch.get("boot_id"))
    ):
        return False
    if previous_kernel_boot(launch["boot_id"], boot_id()):
        return True
    saved = files.json(f"process-{attempt}.json")
    if not isinstance(saved, dict) or set(saved) != {
        "schema",
        "job_id",
        "input_sha256",
        "boot_id",
        "pid",
        "start_ticks",
    }:
        return False
    if (
        saved["schema"] != 1
        or saved["job_id"] != job_id
        or saved["input_sha256"] != input_sha256
        or saved["boot_id"] != launch["boot_id"]
    ):
        return False
    if (
        type(saved["pid"]) is not int
        or not 1 <= saved["pid"] <= 2**31 - 1
        or type(saved["start_ticks"]) is not int
        or saved["start_ticks"] < 1
    ):
        return False
    if not process_present(saved["pid"]):
        return True
    current = read_child(saved["pid"])
    return current is not None and current.start_ticks != saved["start_ticks"]
