"""smiles stage: one typed-context handler in the formal chain."""

from __future__ import annotations

import os
import time
from pathlib import Path

from patent_sar_extractor.application.stage_cache import (
    _bindings_ocsr_digest,
    _fingerprint_matches,
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.artifact_io import load_json as _load_json
from patent_sar_extractor.artifact_io import write_json_atomic as _write_json
from patent_sar_extractor.contracts import (
    OCSR_OBSERVATION_VERSION,
)
from patent_sar_extractor.core.env_runner import run_in_env
from patent_sar_extractor.core.ocsr.engines.decimer_engine import DECIMEREngine
from patent_sar_extractor.paths import PACKAGE_ROOT
from patent_sar_extractor.smiles_artifact import (
    build_smiles_artifact,
    smiles_artifact_is_current,
    smiles_records,
)

from .pipeline_context import PipelineContext
from .pipeline_io import (
    _elapsed_since,
    _owned_worker_outputs,
    _save_log,
    _write_accuracy_failure_marker,
)
from .smiles_policy import (
    _smiles_acceptance_errors,
    _smiles_results_can_be_reused,
)
from .worker_policy import (
    _gpu_env_extra,
    _production_smiles_ocr_options,
)

WORKING_ROOT = Path.cwd()


def execute_smiles(state: PipelineContext) -> None:
    # Stage: smiles
    step = "smiles"
    state.progress.start(step)
    t0 = time.time()
    smiles_dir = state.step_dirs[step]
    state.smiles_json = os.path.join(smiles_dir, "smiles_results.json")
    if not state.active_cpds or state.n_bound == 0:
        print(f"  ⏭ [{step}] 无需 SMILES，跳过")
        _write_json(state.smiles_json, build_smiles_artifact([]))
        n_smiles = 0
        n_valid = 0
    worker_environment = (
        _gpu_env_extra(
            "smiles_engine", gpu_mode=getattr(state.args, "gpu_mode", "auto")
        )
        if state.active_cpds and state.n_bound
        else {}
    )
    smiles_fp = _step_fingerprint(
        step,
        pdf_path=state.args.pdf,
        params={
            **_production_smiles_ocr_options(),
            "ocsr_observation_version": OCSR_OBSERVATION_VERSION,
            "decimer_runtime_fingerprint": DECIMEREngine(
                env_extra=worker_environment
            ).runtime_identity()["fingerprint"]
            if state.active_cpds and state.n_bound
            else None,
            "retry_normalization": True,
            "timeout": 300,
            "no_preprocess": True,
            "smiles_workers": int(getattr(state.args, "smiles_workers", 1) or 1),
            "gpu_mode": getattr(state.args, "gpu_mode", "auto"),
            "bindings_ocsr_digest": _bindings_ocsr_digest(state.bind_json),
        },
    )
    reuse_existing_smiles = False
    if (
        state.active_cpds
        and state.n_bound
        and not state.force
        and _fingerprint_matches(state.smiles_json, smiles_fp)
    ):
        smiles_payload = _load_json(state.smiles_json, {})
        smiles_results = smiles_records(smiles_payload)
        if smiles_artifact_is_current(smiles_payload):
            reuse_existing_smiles, reuse_errors = _smiles_results_can_be_reused(
                smiles_results,
                state.bind_payload,
            )
        else:
            reuse_existing_smiles = False
            reuse_errors = [
                "SMILES output does not match the current production artifact contract."
            ]
        if reuse_existing_smiles:
            n_smiles = len(smiles_results)
            n_valid = sum(1 for r in smiles_results if r.get("rdkit_valid"))
            print(f"  ⏭ [{step}] 已存在且通过当前严格规则，跳过")
            state.progress.mark_checkpoint_reused()
        else:
            print(f"  ↻ [{step}] 已有结果未通过当前严格规则，重跑")
            for error in reuse_errors[:3]:
                print(f"     - {error}")
    if not reuse_existing_smiles and state.active_cpds and state.n_bound:
        os.makedirs(smiles_dir, exist_ok=True)
        smiles_cache = os.path.join(smiles_dir, "smiles_cache.sqlite")
        if state.force and os.path.isfile(smiles_cache):
            from patent_sar_extractor.core.ocsr.smiles_cache import SmilesCache

            purged = SmilesCache(smiles_cache).purge_non_clean()
            print(
                f"     ♻ purged {purged} non-clean SMILES cache entries for force rerun: {smiles_cache}"
            )
        smiles_worker_script = str(PACKAGE_ROOT / "core" / "ocsr" / "run_smiles.py")
        ocsr_options = _production_smiles_ocr_options()
        smiles_args = [
            "--input",
            state.bind_json,
            "--output",
            state.smiles_json,
            "--engine",
            ocsr_options["engine"],
            "--fallback",
            ocsr_options["fallback"],
            "--timeout",
            "300",
            "--cache",
            smiles_cache,
            "--no-preprocess",
            "--retry-normalization",
            "--jobs",
            str(getattr(state.args, "smiles_workers", 1) or 1),
        ]
        with _owned_worker_outputs(
            state.pipeline_log["steps"][step], [state.smiles_json]
        ):
            proc = run_in_env(
                "smiles_engine",
                smiles_worker_script,
                args=smiles_args,
                timeout=7200,
                env_extra=worker_environment,
                stream_output=True,
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()[:1200]
                raise RuntimeError(f"smiles failed: {err}")
        smiles_payload = _load_json(state.smiles_json, {})
        if not smiles_artifact_is_current(smiles_payload):
            raise RuntimeError(
                "SMILES worker returned an incompatible or diagnostic artifact."
            )
        smiles_results = smiles_records(smiles_payload)
        n_smiles = len(smiles_results)
        n_valid = sum(1 for r in smiles_results if r.get("rdkit_valid"))
        _write_step_manifest(state.smiles_json, smiles_fp)
    state.pipeline_log["steps"][step] = {
        **state.pipeline_log["steps"].get(step, {}),
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok" if n_valid or n_smiles == 0 else "warnings",
        "elapsed_s": _elapsed_since(t0),
        "output": state.smiles_json,
        "total": n_smiles,
        "valid": n_valid,
    }
    print(f"     ✅ valid_smiles={n_valid}/{n_smiles}")
    smiles_payload = _load_json(state.smiles_json, {})
    smiles_results = smiles_records(smiles_payload)
    smiles_errors = _smiles_acceptance_errors(smiles_results, state.bind_payload)
    if smiles_errors:
        state.pipeline_log["steps"][step]["status"] = (
            "failed" if state.strict_gates else "warnings"
        )
        state.pipeline_log["steps"][step]["acceptance_errors"] = smiles_errors
        if state.strict_gates:
            state.pipeline_log["status"] = "failed_accuracy_gate"
            _save_log(state.pipeline_log, state.base_dir)
            _write_accuracy_failure_marker(state.base_dir, "smiles", smiles_errors)
            raise RuntimeError(
                "Strict SMILES acceptance gate failed: " + "; ".join(smiles_errors[:8])
            )
        print(
            f"     ⚠ SMILES strict gate warnings={len(smiles_errors)}; continuing review-only partial run"
        )
