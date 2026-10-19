"""Conservative configurable CPU/model budget; never change other applications."""

from __future__ import annotations

import os
from pathlib import Path


def resident_budget_mb() -> int:
    value = int(os.environ.get("PATENTSAR_DECIMER_MAX_RSS_MB", "4096"))
    if not 2048 <= value <= 16384:
        raise ValueError("DECIMER memory budget must be between 2048 and 16384 MiB")
    return value


def check_model_headroom() -> None:
    from patent_sar_extractor.resource_admission import wait_for_memory

    wait_for_memory(min(resident_budget_mb(), 3072))


def _worker_memory_mb(pid: int, field: str) -> float | None:
    try:
        text = Path(f"/proc/{pid}/status").read_text()
    except FileNotFoundError:
        return None
    values = [
        line.split() for line in text.splitlines() if line.startswith(field + ":")
    ]
    if not values:
        return None
    if (
        len(values) != 1
        or len(values[0]) != 3
        or values[0][2] != "kB"
        or not values[0][1].isdecimal()
    ):
        raise ValueError("Invalid owned-process memory telemetry")
    return int(values[0][1]) / 1024


def worker_resident_mb(pid: int) -> float | None:
    return _worker_memory_mb(pid, "VmRSS")


def process_peak_resident_mb() -> float:
    """Post-exec address-space peak, not rusage inherited from a large parent."""
    value = _worker_memory_mb(os.getpid(), "VmHWM")
    if value is None or value <= 0:
        raise RuntimeError("Owned worker peak resident memory is unavailable")
    return value
