"""Qualified research can finish after QA rejection; formal failure is immutable."""

from pathlib import Path

from patent_sar_extractor import contracts

from .stages import read_summary


def completed_qa_rejection(root: Path) -> bool:
    summary = read_summary(root)
    if summary is None:
        return False
    if (
        not contracts.artifact_identity_matches(
            summary, contracts.RUN_SUMMARY_SCHEMA, contracts.RUN_SUMMARY_SCHEMA_VERSION
        )
        or summary.get("status") not in {"review", "failed_qa", "failed_accuracy_gate"}
        or summary.get("main_chain") != list(contracts.CORE_STAGE_ORDER)
    ):
        return False
    steps = summary["steps"]
    if set(steps) != set(contracts.CORE_STAGE_ORDER) or any(
        steps[name].get("status") not in {"ok", "empty", "failed", "warnings"}
        for name in contracts.CORE_STAGE_ORDER
    ):
        return False
    qa = steps["qa"]
    return (
        qa.get("status") == "failed"
        and qa.get("strict_acceptance_ok") is False
        and isinstance(qa.get("hard_errors"), list)
        and bool(qa["hard_errors"])
    )
