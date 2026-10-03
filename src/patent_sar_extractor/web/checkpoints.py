"""Publish bounded completed-stage projections through the existing adapter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from patent_sar_extractor import contracts as core

from .files import SafeFiles
from .models import STAGES


class LiveCheckpoints:
    def __init__(
        self, root: Path, project_id: str, publish: Callable[[str], None]
    ) -> None:
        self.files = SafeFiles(root)
        self.summary = root / "pipeline_summary.json"
        self.project_id = project_id
        self.publish = publish
        self._signature: tuple[int, int] | None = None

    def update(self) -> None:
        try:
            stat = self.summary.stat()
        except FileNotFoundError:
            return
        signature = stat.st_mtime_ns, stat.st_size
        if signature == self._signature:
            return
        summary = self.files.json("pipeline_summary.json")
        if not core.artifact_identity_matches(
            summary, core.RUN_SUMMARY_SCHEMA, core.RUN_SUMMARY_SCHEMA_VERSION
        ):
            return
        self._signature = signature
        # Formal publication remains the terminal owned-process path. Live
        # views show only current checkpoints and cannot invent acceptance.
        if summary.get("status") not in ("running", "qa_pending"):
            return
        steps = summary.get("steps")
        if not isinstance(steps, dict) or not any(
            isinstance(steps.get(stage), dict) and steps[stage].get("status") == "ok"
            for stage in STAGES
        ):
            return
        self.publish(self.project_id)
