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
from patent_sar_extractor.core.env_runner import run_in_env
from patent_sar_extractor.paths import PACKAGE_ROOT

from .pipeline_context import PipelineContext
from .pipeline_io import (
    _elapsed_since,
    _save_log,
    _write_accuracy_failure_marker,
)

WORKING_ROOT = Path.cwd()


def execute_final(state: PipelineContext) -> None:
    # Stage: final
    step = "final"
    state.progress.start(step)
    t0 = time.time()
    final_dir = state.step_dirs[step]
    excel_path = os.path.join(final_dir, f"{state.patent_id}_final.xlsx")
    final_fp = _step_fingerprint(
        step,
        pdf_path=state.args.pdf,
        dependencies=[state.bind_json, state.smiles_json, state.act_json],
        params={"patent_id": state.patent_id},
    )
    if not state.force and _fingerprint_matches(excel_path, final_fp):
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
        ]
        if os.path.isfile(state.act_json):
            final_args.extend(["--activity", state.act_json])
        if not state.strict_gates:
            final_args.append("--allow-partial")
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
        _write_step_manifest(excel_path, final_fp)
    state.pipeline_log["steps"][step] = {
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok",
        "elapsed_s": _elapsed_since(t0),
        "output": final_dir,
        "excel": os.path.isfile(excel_path),
        "sdf": any(Path(final_dir).glob("*.sdf")),
    }
    print("     ✅ final_results ready")
