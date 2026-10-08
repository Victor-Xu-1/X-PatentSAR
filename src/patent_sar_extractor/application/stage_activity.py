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
from patent_sar_extractor.core.activity_join import activity_evidence_errors

from .evidence_review import review_source_evidence
from .pipeline_context import PipelineContext
from .pipeline_io import (
    _elapsed_since,
    _owned_worker_outputs,
)
from .scientific_status import retain_scientific_errors
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
        dependencies=[state.classify_json, state.bind_json],
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
        with _owned_worker_outputs(state.pipeline_log["steps"][step], [state.act_json]):
            _run_activity_rules(
                state.args.pdf,
                state.classification,
                act_dir,
                include_intermediates=getattr(
                    state.args, "include_intermediates", False
                ),
                patent_id=state.patent_id,
                bindings_path=state.bind_json,
            )
        _write_step_manifest(state.act_json, activity_fp)
    state.activity_payload = (
        _load_json(state.act_json, {}) if os.path.isfile(state.act_json) else {}
    )
    activity_errors = activity_evidence_errors(
        state.activity_payload,
        classified_activity_pages=state.classification.get("activity_pages"),
    )
    # Producer-owned metadata is read only. It cannot admit/relabel compounds or
    # turn the source-led structure universe back into a numeric activity filter.
    state.active_cpds = state.activity_payload.get("active_cpds", [])
    if not isinstance(state.active_cpds, list) or any(
        not isinstance(compound, str) for compound in state.active_cpds
    ):
        raise ValueError("Malformed activity producer metadata")
    act_rows = len(state.activity_payload["rows"])
    state.pipeline_log["steps"][step] = {
        **state.pipeline_log["steps"].get(step, {}),
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok" if act_rows else "empty",
        "elapsed_s": _elapsed_since(t0),
        "output": state.act_json,
        "rows": act_rows,
        "active_cpds": len(state.active_cpds),
    }
    print(f"     ✅ rows={act_rows}, active_cpds={len(state.active_cpds)}")
    evidence_review = review_source_evidence(state, activity_errors)
    if evidence_review is not None:
        state.pipeline_log["steps"][step]["evidence_resolution"] = evidence_review
    retain_scientific_errors(state, step, activity_errors)
