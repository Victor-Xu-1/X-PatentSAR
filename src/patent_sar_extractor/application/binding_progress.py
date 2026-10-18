"""Bounded source-work snapshots on the existing owned stage progress channel."""

import time
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    STAGE_PROGRESS_SCHEMA,
    STAGE_PROGRESS_SCHEMA_VERSION,
    schema_ref,
)
from patent_sar_extractor.core.binding_progress import (
    BINDING_SOURCE_PHASES,
    BindingSourcePhase,
)


class BindingProgress:
    def __init__(self, output: str) -> None:
        self.path = Path(output) / "progress.json"
        self._last: tuple[BindingSourcePhase, int, int] | None = None
        self._published_at = 0.0
        # A new producer never borrows transported telemetry as fresh work.
        self._write(None, 0, 0)

    def __call__(self, phase: BindingSourcePhase, completed: int, total: int) -> None:
        if (
            phase not in BINDING_SOURCE_PHASES
            or type(completed) is not int
            or type(total) is not int
            or not 0 <= completed <= total <= 1_000_000
        ):
            raise ValueError("Invalid binding source-work counters")
        previous = self._last
        if previous is not None:
            old_phase, old_count, old_total = previous
            if (
                phase == old_phase
                and (total != old_total or completed < old_count)
                or phase != old_phase
                and (
                    BINDING_SOURCE_PHASES.index(phase)
                    <= BINDING_SOURCE_PHASES.index(old_phase)
                    or old_count != old_total
                )
            ):
                raise ValueError(
                    "Binding source-work cannot regress or skip pending work"
                )
        current = (phase, completed, total)
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
            self._write(phase, completed, total)
            self._published_at = now

    def _write(
        self, phase: BindingSourcePhase | None, completed: int, total: int
    ) -> None:
        write_json_atomic(
            self.path,
            {
                "schema": schema_ref(
                    STAGE_PROGRESS_SCHEMA, STAGE_PROGRESS_SCHEMA_VERSION
                ),
                "stage": "bind",
                "phase": None,
                "source_phase": phase,
                "completed": completed,
                "total": total,
                "cache_hits": 0,
                "failures": 0,
                "device": None,
                "peak_rss_mb": None,
            },
        )
