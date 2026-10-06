"""Bind all independently proved printed identifiers before activity joining."""

from __future__ import annotations

import os
import time
from pathlib import Path

from patent_sar_extractor.contracts import STRUCTURE_BINDER_VERSION
from patent_sar_extractor.core.binding_artifacts import write_binding_result
from patent_sar_extractor.core.formal_structure import SOURCE_EXECUTION_MODE

from .binding_policy import _binding_acceptance_errors, _load_reusable_bindings
from .pipeline_context import PipelineContext
from .pipeline_io import _elapsed_since
from .scientific_status import retain_scientific_errors
from .stage_cache import _step_fingerprint, _write_step_manifest


def execute_bind(state: PipelineContext) -> None:
    step = "bind"
    state.progress.start(step)
    started = time.time()
    directory = state.step_dirs[step]
    state.bind_json = os.path.join(directory, "bindings.json")
    profile = {
        "synthesis_pages": state.structure_pages,
        "cpd_pattern": state.classification.get("cpd_pattern", r"Cpd[-\s]?(\d+)"),
        "cpd_prefix": state.classification.get("cpd_prefix", "Cpd-"),
        "table_layout": state.classification.get("table_layout", "single"),
        "page_count": state.classification.get("page_count", 0),
        "structure_candidate_pages": state.structure_pages,
        "ocr_text_map": state.locator.get("ocr_text_map", {}),
        "ocr_line_map": state.locator.get("ocr_line_map", {}),
        "ocr_cache_path": state.ocr_cache_path,
        "authoritative_structure_table_pages": state.locator.get(
            "structure_table_pages", []
        ),
        "bind_workers": int(getattr(state.args, "bind_workers", 1) or 1),
        "execution_mode": SOURCE_EXECUTION_MODE,
    }
    fingerprint = _step_fingerprint(
        step,
        pdf_path=state.args.pdf,
        dependencies=[state.structures_json, state.locate_json, state.ocr_cache_path],
        params={
            **profile,
            "structure_binder_version": STRUCTURE_BINDER_VERSION,
            "include_intermediates": bool(
                getattr(state.args, "include_intermediates", False)
            ),
        },
    )
    reusable = (
        _load_reusable_bindings(state.bind_json, fingerprint, state.locator)
        if not state.force
        else None
    )
    if reusable is not None:
        state.bind_payload = reusable
        state.progress.mark_checkpoint_reused()
    elif state.n_structures:
        from patent_sar_extractor.core.structure_binder import bind

        state.bind_payload = bind(
            state.args.pdf,
            profile,
            directory,
            state.structures_json,
            include_intermediates=getattr(state.args, "include_intermediates", False),
        )
        _write_step_manifest(state.bind_json, fingerprint)
    else:
        state.bind_payload = write_binding_result(
            Path(directory),
            patent_id=state.patent_id,
            bindings=[],
            detected_style="no_original_structures",
            include_intermediates=False,
            total_structures=0,
            total_compound_blocks=0,
            table_pages=[],
            table_covered_count=0,
            no_binding=[],
            unbound_pages=[],
        )
        _write_step_manifest(state.bind_json, fingerprint)
    state.n_bound = len(state.bind_payload["final_bindings"])
    state.source_cpds = [row["cpd"] for row in state.bind_payload["final_bindings"]]
    state.pipeline_log["steps"][step] = {
        "from_cache": state.progress.checkpoint_reused,
        "status": "ok" if state.n_bound else "empty",
        "output_updated": not state.progress.checkpoint_reused,
        "elapsed_s": _elapsed_since(started),
        "output": state.bind_json,
        "bound": state.n_bound,
        "formal_acceptance_scope": state.bind_payload["formal_acceptance_scope"],
    }
    retain_scientific_errors(
        state, step, _binding_acceptance_errors(state.bind_payload, state.locator)
    )
