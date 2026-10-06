"""Bounded memory admission before model loading; never stops other workloads."""

from __future__ import annotations

import math
import os
import threading
import time
from pathlib import Path

from .artifact_io import write_json_atomic


class ResourceAdmissionError(RuntimeError):
    pass


def available_memory_mb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024
    raise ResourceAdmissionError(
        "Memory headroom could not be measured; no model was loaded."
    )


def publish_resource_wait(observation: dict | None) -> None:
    root, stage = (
        os.environ.get("PATENTSAR_PROGRESS_ROOT"),
        os.environ.get("PATENTSAR_PROGRESS_STAGE"),
    )
    if not root or not stage:
        return
    path = Path(root)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ResourceAdmissionError(
            "Resource progress requires an owned absolute workspace."
        )
    fields = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
    write_json_atomic(
        path / "resource_wait.json",
        {
            "schema": {"name": "patentsar.resource-wait", "version": 1},
            "stage": stage,
            "pid": os.getpid(),
            "start_ticks": int(fields[19]),
            "observed_monotonic": time.monotonic(),
            "observation": observation,
        },
    )


def wait_for_memory(
    required_mb: float,
    *,
    timeout: float = 110,
    cancel: threading.Event | None = None,
    available=None,
    publish=None,
    pause=None,
    clock=None,
) -> None:
    available = available or available_memory_mb
    publish = publish or publish_resource_wait
    pause = pause or time.sleep
    clock = clock or time.monotonic
    if (
        not math.isfinite(required_mb)
        or not 1 <= required_mb <= 16384
        or not math.isfinite(timeout)
        or not 0.05 <= timeout <= 120
    ):
        raise ValueError(
            "Resource admission must have bounded memory/time requirements"
        )
    started = clock()
    waiting = False
    last_publish = float("-inf")
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise ResourceAdmissionError(
                    "Resource admission was cancelled; no model was loaded."
                )
            free = available()
            if type(free) not in {int, float} or not math.isfinite(free) or free < 0:
                raise ResourceAdmissionError("Memory headroom measurement is invalid.")
            if free >= required_mb:
                return
            waited = clock() - started
            if waited >= timeout:
                raise ResourceAdmissionError(
                    "No model was loaded. Memory headroom did not recover within the bounded wait; resume later."
                )
            waiting = True
            if waited - last_publish >= 0.5:
                publish(
                    {
                        "reason": "memory",
                        "required_mb": float(required_mb),
                        "available_mb": float(free),
                        "waited_seconds": max(0.0, waited),
                    }
                )
                last_publish = waited
            pause(min(0.25, timeout - waited))
    finally:
        if waiting:
            publish(None)
