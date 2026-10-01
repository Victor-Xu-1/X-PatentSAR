"""activity stage: one typed-context handler in the formal chain."""

from __future__ import annotations

import os
import time
from pathlib import Path

from patent_sar_extractor.application.stage_cache import (
    _fingerprint_matches,
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.artifact_io import load_json as _load_json
from patent_sar_extractor.contracts import (
    ACTIVITY_EXTRACTOR_VERSION,
)

from .activity_policy import (
    _activity_acceptance_errors,
    _annotate_activity_payload,
)
from .pipeline_context import PipelineContext
from .pipeline_io import (
    _elapsed_since,
    _save_log,
    _write_accuracy_failure_marker,
)
from .worker_policy import (
    _run_activity_rules,
)

WORKING_ROOT = Path.cwd()


def execute_activity(state: PipelineContext) -> None:
    # Stage: activity
    step = "activity"
    state.progress.start(step)
    t0 = time.time()
    act_dir = state.step_dirs[step]
    state.act_json = os.path.join(act_dir, "activity_data.json")
    activity_fp = _step_fingerprint(
        step,
        pdf_path=state.args.pdf,
        dependencies=[state.classify_json],
        params={
            "include_intermediates": bool(
                getattr(state.args, "include_intermediates", False)
            ),
            "activity_pages": state.classification.get("activity_pages", []),
            "ocr_cache_path": state.ocr_cache_path,
            "activity_extractor_version": ACTIVITY_EXTRACTOR_VERSION,
            "patent_id": state.patent_id,
        },
    )
    if not state.force and _fingerprint_matches(state.act_json, activity_fp):
        print(f"  ⏭ [{step}] 已存在，跳过")
        state.progress.mark_checkpoint_reused()
    else:
        os.makedirs(act_dir, exist_ok=True)
        _run_activity_rules(
            state.args.pdf,
            state.classification,
            act_dir,
            include_intermediates=getattr(state.args, "include_intermediates", False),
            patent_id=state.patent_id,
        )
        _write_step_manifest(state.act_json, activity_fp)
    state.active_cpds = (
        _annotate_activity_payload(state.act_json)
        if os.path.isfile(state.act_json)
        else []
    )
    state.activity_payload = (
        _load_json(state.act_json, {}) if os.path.isfile(state.act_json) else {}
    )
    act_rows = len((state.activity_payload or {}).get("rows", []))
    state.pipeline_log["steps"][step] = {
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok" if act_rows else "empty",
        "elapsed_s": _elapsed_since(t0),
        "output": state.act_json,
        "rows": act_rows,
        "active_cpds": len(state.active_cpds),
    }
    print(f"     ✅ rows={act_rows}, active_cpds={len(state.active_cpds)}")
    activity_errors = _activity_acceptance_errors(
        state.activity_payload, state.active_cpds
    )
    if activity_errors:
        state.pipeline_log["steps"][step]["status"] = (
            "failed" if state.strict_gates else "warnings"
        )
        state.pipeline_log["steps"][step]["acceptance_errors"] = activity_errors
        if state.strict_gates:
            state.pipeline_log["status"] = "failed_accuracy_gate"
            _save_log(state.pipeline_log, state.base_dir)
            _write_accuracy_failure_marker(state.base_dir, "activity", activity_errors)
            raise RuntimeError(
                "Strict activity acceptance gate failed: "
                + "; ".join(activity_errors[:8])
            )
        print(
            f"     ⚠ activity strict gate warnings={len(activity_errors)}; continuing review-only partial run"
        )
