"""Progress from persisted core stage facts, never inferred percentages."""

from __future__ import annotations

import math
from pathlib import Path

from .files import SafeFiles
from .models import STAGES, Stage


def read_stages(run_root: Path | None) -> list[Stage]:
    if run_root is None or not run_root.is_dir():
        return [Stage(name=name) for name in STAGES]
    summary = SafeFiles(run_root).json("pipeline_summary.json") or {}
    steps = summary.get("steps", {}) if isinstance(summary, dict) else {}
    if not isinstance(steps, dict):
        steps = {}
    counts = {
        "classify": "page_count",
        "activity": "rows",
        "locate": "selected_pages",
        "structures": "total",
        "bind": "bound",
        "smiles": "total",
        "final": "rows",
        "qa": "count",
    }
    output = []
    for name in STAGES:
        raw = steps.get(name, {})
        if not isinstance(raw, dict):
            raw = {}
        status = raw.get("status", "pending")
        if status not in {"pending", "running", "ok", "empty", "failed", "warnings"}:
            status = "warnings"
        count = raw.get(counts[name])
        if isinstance(count, list):
            count = len(count)
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or not 0 <= count <= 1000000
        ):
            count = None
        duration = raw.get("elapsed_s")
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not math.isfinite(duration)
            or duration < 0
        ):
            duration = None
        output.append(
            Stage(name=name, status=status, count=count, duration_seconds=duration)
        )
    return output
