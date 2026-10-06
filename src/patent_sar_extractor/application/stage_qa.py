"""qa stage: one typed-context handler in the formal chain."""

from __future__ import annotations

import time
from pathlib import Path

from patent_sar_extractor.application.qa_policy import compose_qa_decision
from patent_sar_extractor.contracts import (
    PRODUCT_NAME,
    __version__,
)
from patent_sar_extractor.failures import clear_failure_marker
from patent_sar_extractor.integrations.llm.advisory_qa import run_advisory_qa

from .pipeline_context import PipelineContext
from .pipeline_io import (
    _elapsed_since,
    _save_log,
    _write_accuracy_failure_marker,
)
from .scientific_status import CoreNotAcceptedError

WORKING_ROOT = Path.cwd()


def execute_qa(state: PipelineContext) -> dict:
    # Stage: QA
    step = "qa"
    state.progress.start(step)
    t0 = time.time()
    from patent_sar_extractor.core.qa_report import write_qa_report

    # QA reads the persisted run summary.  Persist the current run before the
    # gate so it never evaluates stale metadata from an earlier execution.
    state.pipeline_log["status"] = "qa_pending"
    _save_log(state.pipeline_log, state.base_dir)
    deterministic_qa = write_qa_report(
        state.base_dir,
        patent_id=state.patent_id,
        ignore_previous_failure_marker=True,
    )
    llm_qa = run_advisory_qa(
        state.base_dir, enabled=not getattr(state.args, "skip_advisory_qa", False)
    )
    qa_decision = compose_qa_decision(deterministic_qa, llm_qa)
    combined_warnings = qa_decision["warnings"]
    qa_ok = bool(qa_decision["ok"])
    acceptance = qa_decision["acceptance"]
    state.pipeline_log["steps"][step] = {
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok"
        if qa_ok
        else "failed"
        if not acceptance.get("ok", False)
        else "warnings",
        "elapsed_s": _elapsed_since(t0),
        "warnings": combined_warnings,
        "deterministic_ok": bool(deterministic_qa.get("ok")),
        "llm_advisory_status": llm_qa.get("status", "unknown"),
        "llm_advisory_assessment": llm_qa.get("assessment", "unavailable"),
        "llm_advisory_warnings": llm_qa.get("warnings", []),
        "strict_acceptance_ok": bool(acceptance.get("ok")),
        "hard_errors": acceptance.get("hard_errors", []),
    }
    print(f"     {'✅' if qa_ok else '⚠️'} warnings={len(combined_warnings)}")

    total_elapsed = sum(
        s.get("elapsed_s", 0) for s in state.pipeline_log["steps"].values()
    )
    state.pipeline_log["status"] = (
        "complete"
        if state.pipeline_log["steps"]["qa"]["status"] == "ok"
        else "failed_accuracy_gate"
    )
    if not qa_ok:
        state.pipeline_log["error"] = {
            "code": "core_not_accepted",
            "message": "Strict source-led acceptance failed",
        }
    state.pipeline_log["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state.pipeline_log["total_elapsed_s"] = round(total_elapsed, 1)
    _save_log(state.pipeline_log, state.base_dir)

    print(f"\n{'=' * 65}")
    print(f"📊 {PRODUCT_NAME} v{__version__} Summary — {state.patent_id}")
    print(f"{'=' * 65}")
    for sn, si in state.pipeline_log["steps"].items():
        icon = (
            "✅"
            if si.get("status") == "ok"
            else "⚠️"
            if si.get("status") in ("warnings", "partial", "empty")
            else "❌"
        )
        print(f"  {icon} {sn:12s}  {si.get('elapsed_s', 0):>6.1f}s")
    print(f"{'─' * 65}")
    print(f"  ⏱ Total: {total_elapsed:.1f}s")
    print(f"  📁 Output: {state.base_dir}")
    print(f"{'=' * 65}")
    if not qa_ok:
        rejection_reasons = acceptance.get("hard_errors", []) or combined_warnings
        if state.strict_gates:
            _write_accuracy_failure_marker(
                state.base_dir, "final_qa", rejection_reasons
            )
            raise CoreNotAcceptedError(
                "Strict final acceptance gate failed: "
                + "; ".join(rejection_reasons[:8])
            )
        print(
            f"  ⚠ Strict final acceptance failed; review-only partial run retained {len(rejection_reasons)} issues"
        )
    if qa_ok:
        clear_failure_marker(state.base_dir)
    return state.pipeline_log
