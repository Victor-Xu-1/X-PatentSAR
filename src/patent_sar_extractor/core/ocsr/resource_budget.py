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
