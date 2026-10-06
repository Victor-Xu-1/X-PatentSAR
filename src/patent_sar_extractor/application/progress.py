"""Persist real stage transitions, including exceptions before a stage returns."""

from __future__ import annotations

import os
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic


class PipelineProgress:
    def __init__(self) -> None:
        self._root: Path | None = None
        self._log: dict | None = None
        self._stage: str | None = None
        self._reused = False

    def bind(self, root: str, log: dict) -> None:
        self._root = Path(root)
        self._log = log

    def start(self, stage: str) -> None:
        if self._root is None or self._log is None:
            raise RuntimeError("Pipeline progress has not been initialized")
        if stage not in self._log["main_chain"]:
            raise ValueError("Unknown extraction stage")
        self._stage = stage
        os.environ["PATENTSAR_PROGRESS_ROOT"] = str(self._root.resolve())
        os.environ["PATENTSAR_PROGRESS_STAGE"] = stage
        self._reused = False
        self._log["steps"][stage] = {"status": "running"}
        write_json_atomic(self._root / "pipeline_summary.json", self._log)

    @property
    def checkpoint_reused(self) -> bool:
        return self._reused

    def mark_checkpoint_reused(self) -> None:
        self._reused = True

    def fail_current(self) -> None:
        if self._root is None or self._log is None or self._stage is None:
            return
        step = self._log["steps"][self._stage]
        step["status"] = "failed"
        if not step.get("acceptance_errors"):
            step["acceptance_errors"] = [
                "Stage execution failed; inspect private run logs."
            ]
        if self._log["status"] != "failed_accuracy_gate":
            self._log["status"] = "failed"
        write_json_atomic(self._root / "pipeline_summary.json", self._log)
