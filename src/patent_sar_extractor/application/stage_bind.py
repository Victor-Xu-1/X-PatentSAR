"""bind stage: one typed-context handler in the formal chain."""

from __future__ import annotations

import os
import time
from pathlib import Path

from patent_sar_extractor.application.stage_cache import (
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.contracts import (
    STRUCTURE_BINDER_VERSION,
)

from .binding_policy import (
    _binding_acceptance_errors,
    _filter_bindings_by_active_cpds,
    _load_reusable_bindings,
    _save_bindings_payload,
)
from .pipeline_context import PipelineContext
from .pipeline_io import (
    _elapsed_since,
    _save_log,
    _write_accuracy_failure_marker,
)

WORKING_ROOT = Path.cwd()


def execute_bind(state: PipelineContext) -> None:
    # Stage: bind
    step = "bind"
    state.progress.start(step)
    t0 = time.time()
    bind_dir = state.step_dirs[step]
    state.bind_json = os.path.join(bind_dir, "bindings.json")
    if not state.active_cpds:
        print(f"  ⏭ [{step}] 无活性化合物，跳过")
        state.bind_payload = {"final_bindings": []}
        _save_bindings_payload(state.bind_json, state.bind_payload)
        state.n_bound = 0
    elif state.n_structures == 0:
        print(f"  ⏭ [{step}] 无结构，跳过")
        state.bind_payload = {"final_bindings": []}
        _save_bindings_payload(state.bind_json, state.bind_payload)
        state.n_bound = 0
    else:
        bind_profile = {
            "synthesis_pages": state.structure_pages,
            "activity_pages": state.classification.get("activity_pages", []),
            "cpd_pattern": state.classification.get("cpd_pattern", r"Cpd[-\s]?(\d+)"),
            "cpd_prefix": state.classification.get("cpd_prefix", "Cpd-"),
            "table_layout": state.classification.get("table_layout", "single"),
            "page_count": state.classification.get("page_count", 0),
            "structure_candidate_pages": state.structure_pages,
            "active_cpds": state.active_cpds,
            "matched_cpds": state.locator.get("matched_cpds", {}),
            "ocr_text_map": state.locator.get("ocr_text_map", {}),
            "ocr_line_map": state.locator.get("ocr_line_map", {}),
            "authoritative_structure_table_pages": state.locator.get(
                "structure_table_pages", []
            ),
            "authoritative_structure_table_cpds": state.locator.get(
                "structure_table_covered_cpds", []
            ),
            "bind_workers": int(getattr(state.args, "bind_workers", 1) or 1),
            "allow_review_bindings": not state.strict_gates,
            "execution_mode": "production_activity_led",
        }
        bind_fp = _step_fingerprint(
            step,
            pdf_path=state.args.pdf,
            dependencies=[
                state.structures_json,
                state.act_json,
                state.locate_json,
                state.ocr_cache_path,
            ],
            params={
                **bind_profile,
                "structure_binder_version": STRUCTURE_BINDER_VERSION,
                "include_intermediates": bool(
                    getattr(state.args, "include_intermediates", False)
                ),
            },
        )
    reusable_bindings = (
        _load_reusable_bindings(
            state.bind_json, bind_fp, state.active_cpds, state.locator
        )
        if state.active_cpds and state.n_structures and not state.force
        else None
    )
    if reusable_bindings is not None:
        state.bind_payload = reusable_bindings
        _save_bindings_payload(state.bind_json, state.bind_payload)
        state.n_bound = len(state.bind_payload.get("final_bindings", []))
        print(f"  ⏭ [{step}] 已存在，跳过")
        state.progress.mark_checkpoint_reused()
    elif state.active_cpds and state.n_structures:
        from patent_sar_extractor.core.structure_binder import bind as binder_bind

        os.makedirs(bind_dir, exist_ok=True)
        state.bind_payload = binder_bind(
            pdf_path=state.args.pdf,
            profile=bind_profile,
            output_dir=bind_dir,
            structures_path=state.structures_json,
            include_intermediates=getattr(state.args, "include_intermediates", False),
        )
        state.bind_payload, removed = _filter_bindings_by_active_cpds(
            state.bind_payload, state.active_cpds
        )
        state.bind_payload.setdefault("activity_gate", {})
        state.bind_payload["activity_gate"]["removed_after_bind"] = removed
        _save_bindings_payload(state.bind_json, state.bind_payload)
        _write_step_manifest(state.bind_json, bind_fp)
        state.n_bound = len(state.bind_payload.get("final_bindings", []))
    state.pipeline_log["steps"][step] = {
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok" if state.n_bound else "empty",
        "elapsed_s": _elapsed_since(t0),
        "output": state.bind_json,
        "bound": state.n_bound,
    }
    print(f"     ✅ bound={state.n_bound}")
    binding_errors = _binding_acceptance_errors(
        state.bind_payload, state.active_cpds, state.locator
    )
    if binding_errors:
        state.pipeline_log["steps"][step]["status"] = (
            "failed" if state.strict_gates else "warnings"
        )
        state.pipeline_log["steps"][step]["acceptance_errors"] = binding_errors
        if state.strict_gates:
            state.pipeline_log["status"] = "failed_accuracy_gate"
            _save_log(state.pipeline_log, state.base_dir)
            _write_accuracy_failure_marker(state.base_dir, "bind", binding_errors)
            raise RuntimeError(
                "Strict binding acceptance gate failed: "
                + "; ".join(binding_errors[:8])
            )
        print(
            f"     ⚠ binding strict gate warnings={len(binding_errors)}; continuing review-only partial run"
        )
