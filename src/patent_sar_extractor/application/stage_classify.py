"""classify stage: one typed-context handler in the formal chain."""

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
    PAGE_CLASSIFIER_VERSION,
    PAGE_OCR_CACHE_SCHEMA,
    PAGE_OCR_CACHE_SCHEMA_VERSION,
    schema_ref,
)
from patent_sar_extractor.core.page_classifier import classify_pdf

from .pipeline_context import PipelineContext
from .pipeline_io import (
    _elapsed_since,
)

WORKING_ROOT = Path.cwd()


def execute_classify(state: PipelineContext) -> None:
    # Stage: deterministic classification in original-PDF page coordinates.
    step = "classify"
    state.progress.start(step)
    t0 = time.time()
    source_cache = getattr(state.args, "reuse_ocr_cache", "")
    if source_cache:
        from patent_sar_extractor.core.page_ocr_cache import inherit_page_ocr_cache

        if state.force:
            raise ValueError(
                "Force recomputation and OCR observation reuse cannot be combined"
            )
        inherited = inherit_page_ocr_cache(
            source_cache,
            os.path.join(state.step_dirs[step], "page_ocr_cache.json"),
            state.args.pdf,
        )
        state.pipeline_log["runtime"]["ocr_observations_inherited"] = inherited
    state.classify_json = os.path.join(
        state.step_dirs[step], "page_classification.json"
    )
    classify_fp = _step_fingerprint(
        step,
        pdf_path=state.args.pdf,
        params={
            "page_classifier_version": PAGE_CLASSIFIER_VERSION,
            "patent_id": state.patent_id,
            "page_ocr_cache_schema": schema_ref(
                PAGE_OCR_CACHE_SCHEMA, PAGE_OCR_CACHE_SCHEMA_VERSION
            ),
        },
    )
    if not state.force and _fingerprint_matches(state.classify_json, classify_fp):
        state.classification = _load_json(state.classify_json, {})
        print(f"  ⏭ [{step}] 已存在，跳过")
        state.progress.mark_checkpoint_reused()
    else:
        state.classification = classify_pdf(
            state.args.pdf, state.step_dirs[step], force_ocr_cache=state.force
        )
        _write_step_manifest(state.classify_json, classify_fp)
    state.ocr_cache_path = state.classification.get(
        "ocr_cache_path", os.path.join(state.step_dirs[step], "page_ocr_cache.json")
    )
    state.pipeline_log["steps"][step] = {
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok",
        "elapsed_s": _elapsed_since(t0),
        "output": state.classify_json,
        "ocr_cache_path": state.ocr_cache_path,
        "page_count": state.classification.get("page_count", 0),
        "synthesis_pages": len(state.classification.get("synthesis_pages", [])),
        "activity_pages": len(state.classification.get("activity_pages", [])),
        "candidate_pages": len(state.classification.get("candidate_pages", [])),
    }
    print(
        f"     ✅ synthesis={len(state.classification.get('synthesis_pages', []))}, activity={len(state.classification.get('activity_pages', []))}, candidates={len(state.classification.get('candidate_pages', []))}"
    )
