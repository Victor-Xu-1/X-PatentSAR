"""structures stage: one typed-context handler in the formal chain."""

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
from patent_sar_extractor.artifact_io import write_json_atomic as _write_json
from patent_sar_extractor.contracts import (
    STRUCTURE_WORKER_VERSION as _STRUCTURE_WORKER_CONTRACT_VERSION,
)
from patent_sar_extractor.contracts import (
    STRUCTURES_SCHEMA,
    STRUCTURES_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.core.env_runner import run_in_env
from patent_sar_extractor.paths import PACKAGE_ROOT

from .pipeline_context import PipelineContext
from .pipeline_io import (
    _elapsed_since,
)
from .structure_cache import (
    _load_reusable_structure_chunk,
    _merge_structure_chunk_metadata,
    _structure_chunk_fingerprint,
    _structure_chunk_size,
)
from .worker_policy import (
    _gpu_env_extra,
)

WORKING_ROOT = Path.cwd()


def execute_structures(state: PipelineContext) -> None:
    # Stage: structures
    step = "structures"
    state.progress.start(step)
    t0 = time.time()
    structures_dir = state.step_dirs[step]
    state.structures_json = os.path.join(structures_dir, "metadata.json")
    if not state.active_cpds:
        print(f"  ⏭ [{step}] 无活性化合物，跳过")
        _write_json(
            state.structures_json,
            {
                **artifact_identity(STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION),
                "patent_number": state.patent_id,
                "total_structures": 0,
                "structures": [],
            },
        )
        state.n_structures = 0
    elif not state.structure_pages:
        print(f"  ⏭ [{step}] 定位器未确认任何结构页，保持空结果并交由验收闸门处理")
        _write_json(
            state.structures_json,
            {
                **artifact_identity(STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION),
                "patent_number": state.patent_id,
                "total_structures": 0,
                "structures": [],
                "reason": "no_locator_confirmed_pages",
            },
        )
        state.n_structures = 0
    else:
        chunk_size = _structure_chunk_size()
        structures_fp = _step_fingerprint(
            step,
            pdf_path=state.args.pdf,
            dependencies=[state.locate_json, state.crop_regions_json],
            params={
                "structure_pages": state.structure_pages,
                "crop_regions": state.locator.get("crop_regions", {}),
                "gpu_mode": getattr(state.args, "gpu_mode", "auto"),
                "structure_chunk_size": chunk_size,
                "structure_worker_contract_version": _STRUCTURE_WORKER_CONTRACT_VERSION,
            },
        )
    if (
        state.active_cpds
        and state.structure_pages
        and not state.force
        and _fingerprint_matches(state.structures_json, structures_fp)
    ):
        structures_meta = _load_json(state.structures_json, {})
        state.n_structures = int(structures_meta.get("total_structures", 0))
        print(f"  ⏭ [{step}] 已存在，跳过")
        state.progress.mark_checkpoint_reused()
    elif state.active_cpds and state.structure_pages:
        os.makedirs(structures_dir, exist_ok=True)
        structure_worker_script = str(
            PACKAGE_ROOT / "workers" / "extract_structures.py"
        )
        if state.structure_pages and len(state.structure_pages) > chunk_size:
            chunk_payloads = []
            chunks_dir = os.path.join(structures_dir, ".chunks")
            os.makedirs(chunks_dir, exist_ok=True)
            for chunk_index, start in enumerate(
                range(0, len(state.structure_pages), chunk_size)
            ):
                chunk_pages = state.structure_pages[start : start + chunk_size]
                chunk_output = os.path.join(chunks_dir, f"chunk_{chunk_index:03d}")
                os.makedirs(chunk_output, exist_ok=True)
                chunk_fingerprint = _structure_chunk_fingerprint(
                    pdf_path=state.args.pdf,
                    dependencies=[state.locate_json, state.crop_regions_json],
                    chunk_index=chunk_index,
                    chunk_pages=chunk_pages,
                    chunk_size=chunk_size,
                    crop_regions=state.locator.get("crop_regions", {}),
                    gpu_mode=getattr(state.args, "gpu_mode", "auto"),
                )
                reusable_chunk = (
                    None
                    if state.force
                    else _load_reusable_structure_chunk(chunk_output, chunk_fingerprint)
                )
                if reusable_chunk is not None:
                    print(
                        f"     ⏭ structure chunk {chunk_index + 1}/"
                        f"{(len(state.structure_pages) + chunk_size - 1) // chunk_size}: "
                        f"{len(chunk_pages)} pages cached",
                        flush=True,
                    )
                    chunk_payloads.append(reusable_chunk)
                    continue
                chunk_args = [
                    "--pdf",
                    state.args.pdf,
                    "--output",
                    chunk_output,
                    "--patent-id",
                    state.patent_id,
                    "--pages",
                    *[str(p) for p in chunk_pages],
                ]
                if state.locator.get("crop_regions"):
                    chunk_args.extend(["--crop-regions", state.crop_regions_json])
                print(
                    f"     … structure chunk {chunk_index + 1}/"
                    f"{(len(state.structure_pages) + chunk_size - 1) // chunk_size}: "
                    f"{len(chunk_pages)} pages",
                    flush=True,
                )
                proc = run_in_env(
                    "decimer",
                    structure_worker_script,
                    args=chunk_args,
                    timeout=1800,
                    cwd=str(WORKING_ROOT),
                    env_extra=_gpu_env_extra(
                        "decimer", gpu_mode=getattr(state.args, "gpu_mode", "auto")
                    ),
                    stream_output=True,
                )
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"structure extraction failed in chunk {chunk_index + 1} "
                        f"(pages={[p + 1 for p in chunk_pages]})"
                    )
                chunk_meta = _load_json(os.path.join(chunk_output, "metadata.json"), {})
                _write_step_manifest(
                    os.path.join(chunk_output, "metadata.json"), chunk_fingerprint
                )
                chunk_payloads.append(chunk_meta)
            structures_meta = _merge_structure_chunk_metadata(
                state.patent_id,
                chunk_payloads,
            )
            _write_json(state.structures_json, structures_meta)
        else:
            structure_worker_args = [
                "--pdf",
                state.args.pdf,
                "--output",
                structures_dir,
                "--patent-id",
                state.patent_id,
                "--pages",
                *[str(p) for p in state.structure_pages],
            ]
            if state.locator.get("crop_regions"):
                structure_worker_args.extend(
                    ["--crop-regions", state.crop_regions_json]
                )
            proc = run_in_env(
                "decimer",
                structure_worker_script,
                args=structure_worker_args,
                timeout=3600,
                cwd=str(WORKING_ROOT),
                env_extra=_gpu_env_extra(
                    "decimer", gpu_mode=getattr(state.args, "gpu_mode", "auto")
                ),
                stream_output=True,
            )
            if proc.returncode != 0:
                raise RuntimeError("structure extraction failed")
        structures_meta = _load_json(state.structures_json, {})
        state.n_structures = int(structures_meta.get("total_structures", 0))
        if state.structure_pages and state.n_structures == 0:
            raise RuntimeError(
                "structure extraction returned 0 structures on non-empty candidate pages; "
                "please inspect DECIMER environment and page selection"
            )
        _write_step_manifest(state.structures_json, structures_fp)
    state.pipeline_log["steps"][step] = {
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok" if state.n_structures else "empty",
        "elapsed_s": _elapsed_since(t0),
        "output": state.structures_json,
        "total": state.n_structures,
    }
    print(f"     ✅ total_structures={state.n_structures}")
