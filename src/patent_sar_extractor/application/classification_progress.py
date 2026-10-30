"""Current producer's bounded telemetry on the existing stage progress channel."""

import time
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    STAGE_PROGRESS_SCHEMA,
    STAGE_PROGRESS_SCHEMA_VERSION,
    schema_ref,
)
from patent_sar_extractor.core.page_progress import PAGE_SOURCE_PHASES, PageSourcePhase


class ClassificationProgress:
    def __init__(self, output: str) -> None:
        self.path = Path(output) / "progress.json"
        self._last: tuple[PageSourcePhase, int, int, int] | None = None
        self._published_at = 0.0
        self._write(None, 0, 0, 0)  # Never borrow transported telemetry as fresh work.

    def __call__(
        self, phase: PageSourcePhase, completed: int, total: int, cache_hits: int
    ) -> None:
        if (
            phase not in PAGE_SOURCE_PHASES
            or any(type(value) is not int for value in (completed, total, cache_hits))
            or not 0 <= cache_hits <= completed <= total <= 1_000_000
        ):
            raise ValueError("Invalid original page-work counters")
        previous = self._last
        if previous is not None:
            old_phase, old_count, old_total, old_hits = previous
            if (
                phase == old_phase
                and (
                    total != old_total
                    or cache_hits != old_hits
                    or completed < old_count
                )
                or phase != old_phase
                and (
                    PAGE_SOURCE_PHASES.index(phase)
                    <= PAGE_SOURCE_PHASES.index(old_phase)
                    or old_count != old_total
                )
            ):
                raise ValueError(
                    "Original page work cannot regress or skip pending work"
                )
        current = (phase, completed, total, cache_hits)
        if current == previous:
            return
        self._last = current
        now = time.monotonic()
        if (
            previous is None
            or previous[0] != phase
            or completed == total
            or now - self._published_at >= 0.5
        ):
            self._write(phase, completed, total, cache_hits)
            self._published_at = now

    def _write(
        self, phase: PageSourcePhase | None, completed: int, total: int, cache_hits: int
    ) -> None:
        write_json_atomic(
            self.path,
            {
                "schema": schema_ref(
                    STAGE_PROGRESS_SCHEMA, STAGE_PROGRESS_SCHEMA_VERSION
                ),
                "stage": "classify",
                "phase": None,
                "source_phase": phase,
                "completed": completed,
                "total": total,
                "cache_hits": cache_hits,
                "failures": 0,
                "device": None,
                "peak_rss_mb": None,
            },
        )
