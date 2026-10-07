"""smiles stage: one typed-context handler in the formal chain."""

from __future__ import annotations

import os
import time
from pathlib import Path

from patent_sar_extractor import contracts as core_contracts
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
    SMILES_SCHEMA_VERSION,
)
from patent_sar_extractor.core.env_runner import run_in_env
from patent_sar_extractor.core.formal_structure import (
    FORMAL_SCOPE,
    SOURCE_EXECUTION_MODE,
    coverage_errors,
)
from patent_sar_extractor.core.ocsr.engines.decimer_engine import DECIMEREngine
from patent_sar_extractor.core.ocsr.engines.molscribe_engine import MolScribeEngine
from patent_sar_extractor.core.ocsr.recognition_inputs import (
    ordered_source_results,
    recognition_inputs,
)
from patent_sar_extractor.paths import PACKAGE_ROOT
from patent_sar_extractor.smiles_artifact import (
    build_smiles_artifact,
    smiles_artifact_is_current,
    smiles_records,
    smiles_source_records,
)

from .pipeline_context import PipelineContext
from .pipeline_io import (
    _elapsed_since,
    _owned_worker_outputs,
)
from .recognition_budget import recognition_timeout
from .scientific_status import retain_scientific_errors
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
    # Malformed ownership is technical failure; a known empty proved catalog
    # remains a scientific rejection and does not start a model.
    coverage_errors(state.bind_payload)
    formal_inputs, supplemental = recognition_inputs(state.bind_payload)
    if supplemental or len(formal_inputs) != state.n_bound:
        raise ValueError("Recognition must uniformly cover the entire proved catalog")
    if state.n_bound == 0:
        print(f"  ⏭ [{step}] 缺少已证实编号结构，识别未启动")
        _write_json(
            state.smiles_json,
            {
                **build_smiles_artifact([]),
                "binding_execution_mode": SOURCE_EXECUTION_MODE,
                "formal_acceptance_scope": FORMAL_SCOPE,
            },
        )
        n_smiles = 0
        n_valid = 0
    worker_environment = (
        _gpu_env_extra(
            "smiles_engine", gpu_mode=getattr(state.args, "gpu_mode", "auto")
        )
        if state.n_bound
        else {}
    )
    smiles_fp = _step_fingerprint(
        step,
        pdf_path=state.args.pdf,
        params={
            **_production_smiles_ocr_options(),
            "ocsr_observation_version": OCSR_OBSERVATION_VERSION,
            "stereo_evidence_version": core_contracts.STEREO_EVIDENCE_VERSION,
            "smiles_schema_version": SMILES_SCHEMA_VERSION,
            "decimer_runtime_fingerprint": DECIMEREngine(
                env_extra=worker_environment
            ).runtime_identity()["fingerprint"]
            if state.n_bound
            else None,
            "retry_normalization": True,
            "constrained_stereo_rescue_version": 1,
            "local_rescue_runtime_fingerprint": (
                MolScribeEngine(env_extra=worker_environment).runtime_identity()[
                    "fingerprint"
                ]
                if state.n_bound
                and MolScribeEngine(env_extra=worker_environment).is_available()
                else None
            ),
            "timeout": 300,
            "no_preprocess": True,
            "smiles_workers": int(getattr(state.args, "smiles_workers", 1) or 1),
            "gpu_mode": getattr(state.args, "gpu_mode", "auto"),
            "bindings_ocsr_digest": _bindings_ocsr_digest(state.bind_json),
        },
    )
    reuse_existing_smiles = False
    if (
        state.n_bound
        and not state.force
        and _fingerprint_matches(state.smiles_json, smiles_fp)
    ):
        smiles_payload = _load_json(state.smiles_json, {})
        smiles_results = smiles_records(smiles_payload)
        if (
            smiles_artifact_is_current(smiles_payload)
            and smiles_payload.get("formal_acceptance_scope") == FORMAL_SCOPE
        ):
            reuse_existing_smiles, reuse_errors = _smiles_results_can_be_reused(
                smiles_results,
                state.bind_payload,
            )
            _, sources = recognition_inputs(state.bind_payload)
            if not ordered_source_results(
                sources, smiles_source_records(smiles_payload)
            ):
                reuse_existing_smiles = False
                reuse_errors.append(
                    "Source recognition does not cover the complete proved catalog."
                )
        else:
            reuse_existing_smiles = False
            reuse_errors = [
                "SMILES output does not match the current production artifact contract."
            ]
        if reuse_existing_smiles:
            all_results = [*smiles_results, *smiles_source_records(smiles_payload)]
            n_smiles = len(all_results)
            n_valid = sum(1 for r in all_results if r.get("OCSR_quality_flag") == "ok")
            print(f"  ⏭ [{step}] 已存在且通过当前严格规则，跳过")
            state.progress.mark_checkpoint_reused()
        else:
            print(f"  ↻ [{step}] 已有结果未通过当前严格规则，重跑")
            for error in reuse_errors[:3]:
                print(f"     - {error}")
    if not reuse_existing_smiles and state.n_bound:
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
            "--csv-output",
            os.path.join(smiles_dir, "smiles_results.csv"),
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
            "--continue-on-scientific-errors",
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
                timeout=recognition_timeout(state.n_bound, state.started_monotonic),
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
        if not ordered_source_results(formal_inputs, smiles_results):
            raise RuntimeError(
                "SMILES worker omitted or misassigned formal catalog observations"
            )
        _, sources = recognition_inputs(state.bind_payload)
        if not ordered_source_results(sources, smiles_source_records(smiles_payload)):
            raise RuntimeError(
                "SMILES worker omitted or misassigned catalog observations."
            )
        all_results = [*smiles_results, *smiles_source_records(smiles_payload)]
        n_smiles = len(all_results)
        n_valid = sum(1 for r in all_results if r.get("OCSR_quality_flag") == "ok")
        smiles_payload.update(
            {
                "binding_execution_mode": SOURCE_EXECUTION_MODE,
                "formal_acceptance_scope": FORMAL_SCOPE,
                "strict_coverage": {
                    "expected_cpds": [row["cpd"] for row in formal_inputs],
                    "expected_structure_ids": [
                        row["structure_id"] for row in formal_inputs
                    ],
                },
            }
        )
        _write_json(state.smiles_json, smiles_payload)
        _write_step_manifest(state.smiles_json, smiles_fp)
    smiles_payload = _load_json(state.smiles_json, {})
    smiles_results = smiles_records(smiles_payload)
    source_results = smiles_source_records(smiles_payload)
    state.pipeline_log["steps"][step] = {
        **state.pipeline_log["steps"].get(step, {}),
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok" if n_valid else "warnings" if n_smiles else "failed",
        "elapsed_s": _elapsed_since(t0),
        "output": state.smiles_json,
        "total": n_smiles,
        "valid": n_valid,
        "formal_total": len(smiles_results),
        "source_total": len(source_results),
        "execution_status": "completed" if state.n_bound else "not_started",
        **({"blocked_by": "bind"} if not state.n_bound else {}),
        "binding_execution_mode": SOURCE_EXECUTION_MODE,
        "formal_acceptance_scope": FORMAL_SCOPE,
        "output_updated": bool(state.pipeline_log["steps"][step].get("output_updated"))
        or state.n_bound == 0,
    }
    if n_smiles:
        print(f"     valid_smiles={n_valid}/{n_smiles}")
    smiles_errors = _smiles_acceptance_errors(smiles_results, state.bind_payload)
    if not state.n_bound:
        smiles_errors.append(
            "No proved printed-ID structures; SMILES recognition was not started."
        )
    retain_scientific_errors(state, step, smiles_errors)
