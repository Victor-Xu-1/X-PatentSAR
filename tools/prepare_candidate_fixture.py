"""Native synthetic originals/controlled worker, never private extraction evidence."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.web.service import WorkspaceService


def prepare_candidates(workspace: Path, state: Path) -> dict[str, str]:
    from test_candidate_projection import CandidateProjectionTests

    case = CandidateProjectionTests()
    case.source_workspace = workspace / "controlled-candidate-originals"
    transcript = io.StringIO()
    try:
        with (
            contextlib.redirect_stdout(transcript),
            contextlib.redirect_stderr(transcript),
        ):
            case.setUp()
            case.view()
        service = WorkspaceService(state)
        project = service.import_run(
            case.output,
            pdf_path=case.pdf,
            title="Controlled candidate observations; not extraction accuracy",
        )
        rows = service.results(project.id).items
        if (
            len(rows) != 2
            or any(
                row.smiles is not None
                or row.activities
                or row.identifier_label is not None
                or row.recognition.quality_flag != "unassigned_source_identity"
                for row in rows
            )
            or project.acceptance.state == "accepted"
        ):
            raise AssertionError(
                "Controlled source fixture changed scientific admission"
            )
        values = {
            "PATENTSAR_WEB_STATE_DIR": str(state),
            "PATENTSAR_CONFIG_DIR": str(workspace / "config"),
            "PATENTSAR_E2E_BASE_URL": "http://127.0.0.1:18766",
            "PATENTSAR_E2E_RUN_JOBS": "0",
            "PATENTSAR_E2E_CANDIDATE_PROJECT_ID": project.id,
            "PATENTSAR_E2E_SOURCE_PROJECT_ID": project.id,
        }
        write_json_atomic(
            workspace / "browser-fixture.json",
            {
                "controlled_adapter_fixture": True,
                "native_originals": True,
                "controlled_worker_protocol": True,
                "real_model_execution": False,
                "scientific_acceptance_evidence": False,
                "read_only_browser_scope": True,
                **values,
            },
        )
        return values
    finally:
        case.doCleanups()
        (workspace / "candidate-fixture.log").write_text(
            transcript.getvalue(), encoding="utf-8"
        )
