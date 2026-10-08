"""Fresh installed-stack browser control state; no provider/scientific execution."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.integrations.llm.api_failures import APIProblem
from patent_sar_extractor.integrations.llm.evidence_resolution import EvidenceCallBudget
from patent_sar_extractor.integrations.llm.job_context import read_context
from patent_sar_extractor.integrations.llm.job_health import record_fault
from patent_sar_extractor.web.app import create_app
from patent_sar_extractor.web.jobs import JobQueue
from patent_sar_extractor.web.llm_settings import LLMSettingsService


def prepare_recovery(workspace: Path, state: Path, pdf: Path) -> dict[str, str]:
    config = workspace / "config"
    origin = "http://127.0.0.1:18765"
    settings = LLMSettingsService(config)
    runner = Mock()
    runner.start.side_effect = AssertionError(
        "Browser fixture must not start a scientific process"
    )
    with (
        patch.dict(os.environ, {"PATENTSAR_CONFIG_DIR": str(config)}, clear=True),
        patch.object(JobQueue, "_consume", lambda queue: queue.shutdown.wait()),
        TestClient(
            create_app(
                state,
                port=18765,
                runner=runner,
                llm_settings_service=settings,
                environment_catalog=list,
            ),
            base_url=origin,
        ) as client,
    ):
        token = client.get("/api/v1/session").json()["csrf_token"]
        client.headers.update({"Origin": origin, "X-CSRF-Token": token})
        body = {
            "expected_revision": 0,
            "endpoint": "https://recovery-fixture.invalid/v1",
            "model": "synthetic-transport-only",
            "mode": "on-error",
            "data_consent": True,
            "api_key": "synthetic-old-key-not-a-provider-credential",
        }
        saved = client.put("/api/v1/llm/settings", json=body)
        saved.raise_for_status()
        project = client.post(
            "/api/v1/projects?filename=controlled-recovery.pdf&title=Controlled%20API%20recovery%20(not%20scientific%20results)",
            content=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf"},
        )
        project.raise_for_status()
        project_id = project.json()["id"]
        created = client.post(
            f"/api/v1/projects/{project_id}/jobs", json={"include_admet": False}
        )
        created.raise_for_status()
        job_id = created.json()["id"]
        path = state / "llm" / f"{job_id}.policy.json"
        context = read_context(path)
        budget = EvidenceCallBudget(context.job_id, ledger=context.ledger)
        assert budget.acquire()
        try:
            assert budget.reserve(8)  # Simulated charged-attempt count, never HTTP.
            record_fault(
                context.ledger, context.job_id, APIProblem("authentication_failed", 401)
            )
        finally:
            budget.release()
        client.post(f"/api/v1/jobs/{job_id}/cancel").raise_for_status()
        client.put(
            "/api/v1/llm/settings",
            json={
                **body,
                "expected_revision": 1,
                "api_key": "synthetic-new-key-not-a-provider-credential",
            },
        ).raise_for_status()
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        assert (
            job["llm_recovery"]["can_reauthorize"]
            and job["llm_recovery"]["remaining_calls"] == 7
        )
    runner.start.assert_not_called()
    write_json_atomic(
        workspace / "recovery-control.json",
        {
            "synthetic_control": True,
            "scientific_acceptance_evidence": False,
            "model_or_provider_calls": 0,
            "quota_count_is_simulated": True,
            "project_id": project_id,
            "job_id": job_id,
            "immutable_policy_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    )
    return {
        "PATENTSAR_WEB_STATE_DIR": str(state),
        "PATENTSAR_CONFIG_DIR": str(config),
        "PATENTSAR_E2E_BASE_URL": "http://127.0.0.1:18766",
        "PATENTSAR_E2E_RECOVERY_JOB_ID": job_id,
        "PATENTSAR_E2E_RECOVERY_STACK": "synthetic-isolated-state",
        "PATENTSAR_E2E_RUN_JOBS": "0",
    }
