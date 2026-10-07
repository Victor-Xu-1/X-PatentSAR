"""A finite workload budget within the parent pipeline's 24-hour lifetime."""

from __future__ import annotations

import math
import time

MAX_PIPELINE_SECONDS = 24 * 60 * 60
PER_RECORD_SECONDS = 300


def recognition_timeout(records: int, started_monotonic: float) -> int:
    if type(records) is not int or records < 0 or not math.isfinite(started_monotonic):
        raise ValueError("Invalid recognition workload/lifetime")
    remaining = int(
        MAX_PIPELINE_SECONDS - max(0.0, time.monotonic() - started_monotonic)
    )
    if remaining <= 0:
        raise TimeoutError("The parent pipeline's 24-hour lifetime has expired")
    # The local rescue queue is serial and capped, never a per-record ensemble.
    workload = max(1800, 600 + records * PER_RECORD_SECONDS + min(records, 8) * 60)
    return min(workload, remaining, MAX_PIPELINE_SECONDS)
