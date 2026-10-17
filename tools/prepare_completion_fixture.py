"""Isolated saved-source browser adapter; never a real patent or model run."""

from __future__ import annotations

import json
from pathlib import Path

from patent_sar_extractor.web.service import WorkspaceService
from patent_sar_extractor.web.storage import now


def prepare_completion(workspace: Path, state: Path, pdf: Path) -> dict[str, str]:
    # Test-only adapters exercise the real observation store/projection. The
    # converter and ADMET outputs are explicit controlled observations, not
    # scientific inference or a new production seed endpoint.
    from test_existing_compound_completion import (
        ControlledConverter,
        ExistingCompoundCompletionTests,
    )
    from test_historical_source_read import HistoricalSourceReadTests
    from test_web_support import artifact_run

    values = {
        "PATENTSAR_WEB_STATE_DIR": str(state),
        "PATENTSAR_CONFIG_DIR": str(workspace / "config"),
        "PATENTSAR_E2E_BASE_URL": "http://127.0.0.1:18766",
        "PATENTSAR_E2E_RUN_JOBS": "0",
    }
    for kind in ("pending", "complete", "conflicting", "historical"):
        case = ExistingCompoundCompletionTests()
        case.run = artifact_run(workspace / f"controlled-{kind}", pdf, rows=1)
        case.service = WorkspaceService(state)
        case.project = case.service.import_run(
            case.run,
            pdf_path=pdf,
            title=f"Controlled {kind} source adapter; not extraction evidence",
        )
        job = case.pending_reprints()
        if kind not in {"pending", "historical"}:
            if kind == "conflicting":
                ControlledConverter.raw_by_source = {"proved-reprint": "CCC"}
            case.complete(job)
        if kind == "historical":
            binding_path = case.run / "structure_bindings/bindings.json"
            HistoricalSourceReadTests.downgrade(
                binding_path, json.loads(binding_path.read_text())
            )
            case.service.refresh(case.project.id)
        # No queued/live process survives fixture construction. The browser may
        # only read these isolated sources; it never submits scientific tasks.
        with case.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status=?,finished_at=? WHERE id=?",
                (
                    "cancelled" if kind in {"pending", "historical"} else "complete",
                    now(),
                    job["id"],
                ),
            )
        values[f"PATENTSAR_E2E_COMPLETION_{kind.upper()}_PROJECT"] = case.project.id
    values["PATENTSAR_E2E_SOURCE_PROJECT_ID"] = values[
        "PATENTSAR_E2E_COMPLETION_COMPLETE_PROJECT"
    ]
    (workspace / "browser-fixture.json").write_text(
        json.dumps(
            {
                "controlled_adapter_fixture": True,
                "scientific_acceptance_evidence": False,
                "read_only_browser_scope": True,
                "real_model_execution": False,
                **values,
            },
            indent=2,
        )
        + "\n"
    )
    return values
