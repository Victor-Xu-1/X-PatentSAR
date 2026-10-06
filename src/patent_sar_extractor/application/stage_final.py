"""final stage: one typed-context handler in the formal chain."""

from __future__ import annotations

import os
import time
from pathlib import Path

from patent_sar_extractor.application.stage_cache import (
    _fingerprint_matches,
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.env_runner import run_in_env
from patent_sar_extractor.core.formal_structure import (
    FORMAL_SCOPE,
    SOURCE_EXECUTION_MODE,
)
from patent_sar_extractor.paths import PACKAGE_ROOT

from .pipeline_context import PipelineContext
from .pipeline_io import (
    _elapsed_since,
    _require_updated_worker_output,
    _save_log,
    _worker_output_state,
    _write_accuracy_failure_marker,
)
from .scientific_status import retain_scientific_errors

WORKING_ROOT = Path.cwd()


def execute_final(state: PipelineContext) -> None:
    # Stage: final
    step = "final"
    state.progress.start(step)
    t0 = time.time()
    final_dir = state.step_dirs[step]
    excel_path = os.path.join(final_dir, f"{state.patent_id}_final.xlsx")
    sdf_path = os.path.join(final_dir, f"{state.patent_id}_final.sdf")
    receipt_path = os.path.join(final_dir, "export_validation.json")
    final_fp = _step_fingerprint(
        step,
        pdf_path=state.args.pdf,
        dependencies=[
            state.bind_json,
            state.smiles_json,
            state.act_json,
            state.classify_json,
        ],
        params={"patent_id": state.patent_id},
    )
    if (
        not state.force
        and _fingerprint_matches(excel_path, final_fp)
        and os.path.isfile(receipt_path)
    ):
        print(f"  ⏭ [{step}] 已存在，跳过")
        state.progress.mark_checkpoint_reused()
    else:
        os.makedirs(final_dir, exist_ok=True)
        final_worker_script = str(PACKAGE_ROOT / "workers" / "gen_final_results.py")
        final_args = [
            "--bindings",
            state.bind_json,
            "--smiles",
            state.smiles_json,
            "--output-dir",
            final_dir,
            "--patent",
            state.patent_id,
            "--classification",
            state.classify_json,
            "--continue-on-scientific-errors",
        ]
        if os.path.isfile(state.act_json):
            final_args.extend(["--activity", state.act_json])
        previous_excel = _worker_output_state(excel_path)
        previous_sdf = _worker_output_state(sdf_path)
        previous_receipt = _worker_output_state(receipt_path)
        proc = run_in_env("base", final_worker_script, args=final_args, timeout=600)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:1200]
            final_errors = [
                f"Final export failed strict validation or generation: {err}"
            ]
            state.pipeline_log["steps"][step] = {
                "from_cache": state.progress.checkpoint_reused,
                "status": "failed",
                "elapsed_s": _elapsed_since(t0),
                "output": final_dir,
                "acceptance_errors": final_errors,
            }
            state.pipeline_log["status"] = "failed_accuracy_gate"
            _save_log(state.pipeline_log, state.base_dir)
            _write_accuracy_failure_marker(state.base_dir, "final_export", final_errors)
            raise RuntimeError(f"final results failed: {err}")
        _require_updated_worker_output(excel_path, previous_excel)
        _require_updated_worker_output(sdf_path, previous_sdf)
        _require_updated_worker_output(receipt_path, previous_receipt)
        _write_step_manifest(excel_path, final_fp)
    state.pipeline_log["steps"][step] = {
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok",
        "output_updated": not state.progress.checkpoint_reused,
        "elapsed_s": _elapsed_since(t0),
        "output": final_dir,
        "excel": os.path.isfile(excel_path),
        "sdf": any(Path(final_dir).glob("*.sdf")),
        "execution_mode": SOURCE_EXECUTION_MODE,
        "formal_acceptance_scope": FORMAL_SCOPE,
    }
    receipt = load_json(receipt_path, {})
    if (
        not isinstance(receipt, dict)
        or receipt.get("execution_mode") != SOURCE_EXECUTION_MODE
        or receipt.get("formal_acceptance_scope") != FORMAL_SCOPE
    ):
        raise ValueError("Malformed source-led export coverage receipt")
    errors = receipt.get("hard_errors")
    if not isinstance(errors, list) or any(
        not isinstance(error, str) for error in errors
    ):
        raise ValueError("Malformed export validation findings")
    state.pipeline_log["steps"][step]["strict_coverage"] = receipt["strict_coverage"]
    retain_scientific_errors(state, step, errors)
    print("     ✅ final_results ready")
