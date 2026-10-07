"""Atomic actual conversion counters, not predicted completion or chemistry QA."""

from __future__ import annotations

import math
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    STAGE_PROGRESS_SCHEMA,
    STAGE_PROGRESS_SCHEMA_VERSION,
)


class ConversionProgress:
    def __init__(self, path: str, total: int):
        self.path = Path(path) if path else None
        self.payload = {
            "schema": {
                "name": STAGE_PROGRESS_SCHEMA,
                "version": STAGE_PROGRESS_SCHEMA_VERSION,
            },
            "stage": "smiles",
            "completed": 0,
            "total": total,
            "cache_hits": 0,
            "failures": 0,
            "device": None,
            "peak_rss_mb": None,
        }
        self.publish()

    def publish(self) -> None:
        if self.path:
            write_json_atomic(self.path, self.payload)

    def record(self, result: dict) -> None:
        self.payload["completed"] += 1
        attempts = result.get("engine_attempts", [])
        cached = any(attempt.get("from_cache") for attempt in attempts)
        self.payload["cache_hits"] += int(cached)
        self.payload["failures"] += int(result.get("OCSR_status") != "success")
        if not cached:
            if result.get("device") in {"cpu", "gpu"}:
                self.payload["device"] = result["device"]
            peak = result.get("peak_rss_mb")
            if (
                isinstance(peak, (float, int))
                and not isinstance(peak, bool)
                and math.isfinite(peak)
                and peak >= 0
            ):
                self.payload["peak_rss_mb"] = max(
                    self.payload["peak_rss_mb"] or 0, peak
                )
        self.publish()

    def replace(self, before: dict, after: dict) -> None:
        """A checked rescue updates an existing observation, never total/completed."""
        self.payload["failures"] += int(after.get("OCSR_status") != "success") - int(
            before.get("OCSR_status") != "success"
        )
        peak = after.get("peak_rss_mb")
        if type(peak) in {int, float} and math.isfinite(peak) and peak >= 0:
            self.payload["peak_rss_mb"] = max(self.payload["peak_rss_mb"] or 0, peak)
        self.publish()
