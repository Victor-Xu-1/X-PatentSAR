"""Single ordered stage registry; no alternate extraction or acceptance path."""

from __future__ import annotations

import os
import re
import time

from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.contracts import (
    CORE_STAGE_ORDER,
    PRODUCT_NAME,
    RUN_SUMMARY_SCHEMA,
    RUN_SUMMARY_SCHEMA_VERSION,
    STRUCTURE_BINDER_VERSION,
    __version__,
    artifact_identity,
)
from patent_sar_extractor.paths import state_dir

from .pipeline_context import PipelineContext
from .pipeline_io import (
    _load_io_config,
    _strict_gates_enabled,
)
from .stage_activity import execute_activity
from .stage_bind import execute_bind
from .stage_classify import execute_classify
from .stage_final import execute_final
from .stage_locate import execute_locate
from .stage_qa import execute_qa
from .stage_smiles import execute_smiles
from .stage_structures import execute_structures


def execute_pipeline(args, progress: PipelineProgress) -> dict:
    state = PipelineContext(args=args, progress=progress)
    provided_patent_id = getattr(state.args, "patent_id", None)
    # Explicit unknown identity is owned by the task, not an invitation to
    # replace it with the uploader's temporary filename. Standalone omission
    # retains the existing filename inference.
    state.patent_id = (
        provided_patent_id
        if provided_patent_id is not None
        else (
            re.search(r"(WO\d{6,})", state.args.pdf).group(1)
            if re.search(r"(WO\d{6,})", state.args.pdf)
            else os.path.splitext(os.path.basename(state.args.pdf))[0]
        )
    )
    if not state.patent_id and not state.args.output:
        raise ValueError(
            "An empty patent identifier requires an explicit output directory."
        )
    io_cfg = _load_io_config()
    state.base_dir = state.args.output or (
        os.path.join(io_cfg.get("output_dir", ""), state.patent_id)
        if io_cfg.get("output_dir")
        else str(state_dir() / "runs" / state.patent_id)
    )
    state.force = getattr(state.args, "force", False)
    state.strict_gates = _strict_gates_enabled(state.args)

    state.step_dirs = {
        "classify": os.path.join(state.base_dir, "page_classification"),
        "activity": os.path.join(state.base_dir, "activity"),
        "locate": os.path.join(state.base_dir, "structure_pages"),
        "structures": os.path.join(state.base_dir, "structures"),
        "bind": os.path.join(state.base_dir, "structure_bindings"),
        "smiles": os.path.join(state.base_dir, "smiles"),
        "final": os.path.join(state.base_dir, "final_results"),
    }

    print(f"{'=' * 65}")
    print(f"🚀 {PRODUCT_NAME} v{__version__} — {state.patent_id}")
    print(f"{'=' * 65}")
    print(f"  PDF:      {state.args.pdf}")
    print(f"  Output:   {state.base_dir}")
    print(f"  Force:    {'yes' if state.force else 'no (skip completed)'}")
    print()

    state.pipeline_log = {
        **artifact_identity(RUN_SUMMARY_SCHEMA, RUN_SUMMARY_SCHEMA_VERSION),
        "patent_id": state.patent_id,
        "input_pdf": state.args.pdf,
        "output_dir": state.base_dir,
        "steps": {},
        "status": "running",
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "main_chain": list(CORE_STAGE_ORDER),
        "runtime": {
            "locate_workers": int(getattr(state.args, "locate_workers", 1) or 1),
            "bind_workers": int(getattr(state.args, "bind_workers", 1) or 1),
            "structure_binder_version": STRUCTURE_BINDER_VERSION,
            "smiles_workers": int(getattr(state.args, "smiles_workers", 1) or 1),
            "gpu_mode": getattr(state.args, "gpu_mode", "auto"),
            "acceptance_mode": "strict_fail_closed"
            if state.strict_gates
            else "review_only_partial",
        },
    }

    state.progress.bind(state.base_dir, state.pipeline_log)

    handlers = {
        "classify": execute_classify,
        "locate": execute_locate,
        "structures": execute_structures,
        "bind": execute_bind,
        "activity": execute_activity,
        "smiles": execute_smiles,
        "final": execute_final,
        "qa": execute_qa,
    }
    result = None
    for stage in CORE_STAGE_ORDER:
        result = handlers[stage](state)
    return result
