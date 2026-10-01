"""Persist real stage transitions, including exceptions before a stage returns."""

from __future__ import annotations

from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic


class PipelineProgress:
    def __init__(self) -> None:
        self._root: Path | None = None
        self._log: dict | None = None
        self._stage: str | None = None

    def bind(self, root: str, log: dict) -> None:
        self._root = Path(root)
        self._log = log

    def start(self, stage: str) -> None:
        if self._root is None or self._log is None:
            raise RuntimeError("Pipeline progress has not been initialized")
        if stage not in self._log["main_chain"]:
            raise ValueError("Unknown extraction stage")
        self._stage = stage
        self._log["steps"][stage] = {"status": "running"}
        write_json_atomic(self._root / "pipeline_summary.json", self._log)

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
