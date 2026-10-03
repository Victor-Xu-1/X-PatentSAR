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
    available = next(
        (
            int(line.split()[1])
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemAvailable:")
        ),
        None,
    )
    required = min(resident_budget_mb(), 3072) * 1024
    if available is None or available < required:
        raise RuntimeError(
            "Insufficient free memory for DECIMER; release other workloads or retry later. No model was loaded."
        )


def worker_resident_mb(pid: int) -> float | None:
    try:
        text = Path(f"/proc/{pid}/status").read_text()
    except FileNotFoundError:
        return None
    return next(
        (
            int(line.split()[1]) / 1024
            for line in text.splitlines()
            if line.startswith("VmRSS:")
        ),
        None,
    )
