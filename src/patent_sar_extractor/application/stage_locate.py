"""locate stage: one typed-context handler in the formal chain."""

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
    STRUCTURE_LOCATOR_VERSION as _STRUCTURE_LOCATOR_CONTRACT_VERSION,
)
from patent_sar_extractor.core.structure_page_locator import (
    STRUCTURE_COVERAGE_POLICY,
    locate_structure_pages,
)

from .pipeline_context import PipelineContext
from .pipeline_io import (
    _elapsed_since,
)

WORKING_ROOT = Path.cwd()


def execute_locate(state: PipelineContext) -> None:
    # Stage: locate structure pages
    step = "locate"
    state.progress.start(step)
    t0 = time.time()
    state.locate_json = os.path.join(state.step_dirs[step], "locator.json")
    locate_fp = _step_fingerprint(
        step,
        pdf_path=state.args.pdf,
        dependencies=[state.classify_json, state.ocr_cache_path],
        params={
            "locate_workers": int(getattr(state.args, "locate_workers", 1) or 1),
            "structure_locator_contract_version": _STRUCTURE_LOCATOR_CONTRACT_VERSION,
            "structure_coverage_policy": STRUCTURE_COVERAGE_POLICY,
        },
    )
    if not state.force and _fingerprint_matches(state.locate_json, locate_fp):
        state.locator = _load_json(state.locate_json, {})
        print(f"  ⏭ [{step}] 已存在，跳过")
        state.progress.mark_checkpoint_reused()
    else:
        state.locator = locate_structure_pages(
            state.args.pdf,
            state.classification,
            [],
            state.locate_json,
            workers=int(getattr(state.args, "locate_workers", 1) or 1),
            ocr_cache_path=state.ocr_cache_path,
        )
        _write_step_manifest(state.locate_json, locate_fp)
    state.structure_pages = state.locator.get("selected_pages", [])
    state.crop_regions_json = os.path.join(state.step_dirs[step], "crop_regions.json")
    _write_json(state.crop_regions_json, state.locator.get("crop_regions", {}))
    state.pipeline_log["steps"][step] = {
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok" if state.structure_pages else "empty",
        "elapsed_s": _elapsed_since(t0),
        "output": state.locate_json,
        "crop_regions": state.crop_regions_json,
        "candidate_pages": len(state.locator.get("candidate_pool", [])),
        "selected_pages": len(state.structure_pages),
        "unmatched_cpds": len(state.locator.get("unmatched_cpds", [])),
        "coverage_policy": state.locator.get("coverage_policy"),
    }
    print(f"     ✅ selected_pages={len(state.structure_pages)}")
