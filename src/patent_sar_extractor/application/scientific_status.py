"""Retain scientific rejection while qualified observations continue to QA."""

from __future__ import annotations

from .pipeline_context import PipelineContext
from .pipeline_io import _save_log, _write_accuracy_failure_marker


class CoreNotAcceptedError(RuntimeError):
    code = "core_not_accepted"


def retain_scientific_errors(
    state: PipelineContext, stage: str, errors: list[str]
) -> None:
    if not errors:
        return
    state.scientific_errors[stage] = list(dict.fromkeys(errors))
    state.pipeline_log["scientific_errors"] = dict(state.scientific_errors)
    state.pipeline_log["steps"][stage].update(
        {
            "status": "failed",
            "acceptance_errors": state.scientific_errors[stage],
        }
    )
    _save_log(state.pipeline_log, state.base_dir)
    _write_accuracy_failure_marker(
        state.base_dir,
        stage,
        [
            f"{name}: {message}"
            for name, findings in state.scientific_errors.items()
            for message in findings
        ],
    )
