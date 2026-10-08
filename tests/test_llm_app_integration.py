"""Real app/security/queue persistence; synthetic originals and bounded wire stubs."""

from __future__ import annotations

import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import fitz
import yaml
from fastapi.testclient import TestClient

from patent_sar_extractor.integrations.llm import client as llm_client
from patent_sar_extractor.integrations.llm.api_failures import (
    APIProblem,
    APIRequestError,
)
from patent_sar_extractor.integrations.llm.evidence_resolution import (
    EvidenceCallBudget,
    EvidenceCandidate,
    EvidenceObservation,
    EvidenceRequest,
    resolve_evidence,
)
from patent_sar_extractor.integrations.llm.job_context import read_context
from patent_sar_extractor.web.analysis_runtime import AnalysisSettings
from patent_sar_extractor.web.app import create_app
from patent_sar_extractor.web.jobs import JobQueue
from patent_sar_extractor.web.llm_settings import LLMSettingsService

BASE, KEY = "http://127.0.0.1:18765", "synthetic-app-only-key"
SETTINGS = "/api/v1/llm/settings"


class LLMAppIntegrationTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.getenv("PATENTSAR_WEB_TEST_ROOT", "/srv/wsl/tmp/llm-app-tests"))
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = tempfile.TemporaryDirectory(prefix="app-", dir=root)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "config"
        self.state = self.root / "state"
        self.settings = LLMSettingsService(self.config)
        self.enterContext(
            patch.dict(
                os.environ, {"PATENTSAR_CONFIG_DIR": str(self.config)}, clear=True
            )
        )
        self.enterContext(
            patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS"))
        )
        self.enterContext(
            patch.object(
                llm_client.requests,
                "post",
                side_effect=AssertionError("No direct HTTP"),
            )
        )
        self.post = self.enterContext(
            patch.object(llm_client, "bounded_post", side_effect=self.wire)
        )
        # Real queue lifecycle, but never start extraction/model processes.
        self.enterContext(
            patch.object(JobQueue, "_consume", lambda queue: queue.shutdown.wait())
        )
        self.runner = Mock()
        self.runner.start.side_effect = AssertionError("No scientific process")
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((20, 30), "Synthetic API queue original, not a patent.")
            self.pdf = document.tobytes()

    @staticmethod
    def wire(*args, **kwargs):
        payload = kwargs["json"]
        properties = payload["response_format"]["json_schema"]["schema"]["properties"]
        content = (
            payload["messages"][-1]["content"]
            if "nonce" in properties
            else json.dumps(
                {
                    "candidates": [
                        {
                            "candidate_id": "candidate",
                            "observation_ids": ["observation"],
                        }
                    ]
                }
            )
        )
        choice = {"message": {"content": content}, "finish_reason": "stop"}
        return json.dumps({"choices": [choice]}).encode()

    def app_client(self, *, default=False):
        injected = {} if default else {"llm_settings_service": self.settings}
        app = create_app(
            self.state,
            port=18765,
            runner=self.runner,
            analysis_settings=AnalysisSettings(),
            environment_catalog=list,
            **injected,
        )
        return self.enterContext(TestClient(app, base_url=BASE))

    def authenticate(self, client):
        token = client.get("/api/v1/session").json()["csrf_token"]
        client.headers.update({"Origin": BASE, "X-CSRF-Token": token})

    def save(self, client, **changes):
        data = {
            "expected_revision": 0,
            "endpoint": "https://api.example.org/v1",
            "model": "synthetic-v1",
            "mode": "quality",
            "data_consent": True,
            "api_key": KEY,
            **changes,
        }
        response = client.put(SETTINGS, json=data)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(KEY, response.text)
        return response.json()

    def enqueue(self, client, *, project=None, resume=None):
        if project is None:
            uploaded = client.post(
                "/api/v1/projects?filename=synthetic.pdf",
                content=self.pdf,
                headers={"Content-Type": "application/pdf"},
            )
            self.assertEqual(uploaded.status_code, 201, uploaded.text)
            project = uploaded.json()["id"]
        body = {"include_admet": False}
        if resume:
            body["resume_job_id"] = resume
        response = client.post(f"/api/v1/projects/{project}/jobs", json=body)
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()["id"]
        spec = client.app.state.queue._spec(job)
        path = self.state / "llm" / f"{spec.llm_context_id}.policy.json"
        return project, job, spec, read_context(path), path

    def resolve(self, context):
        request = EvidenceRequest(
            job_id=context.job_id,
            original_sha256=context.original_sha256,
            task="heading-owner",
            trigger="quality",
            observations=(
                EvidenceObservation("observation", "text", "Synthetic evidence"),
            ),
            candidates=(
                EvidenceCandidate("candidate", "Supplied choice", ("observation",)),
            ),
        )
        budget = EvidenceCallBudget(
            context.job_id, context.policy.max_calls, ledger=context.ledger
        )
        return resolve_evidence(request, budget, config=context.policy), budget

    def test_injection_routes_auth_csrf_nonce_and_redaction(self):
        client = self.app_client()
        self.assertIs(client.app.state.llm_settings, self.settings)
        self.assertIs(client.app.state.queue.llm_policy.__self__, self.settings)
        self.assertEqual(client.get(SETTINGS).status_code, 401)
        self.authenticate(client)
        blocked = client.put(SETTINGS, json={}, headers={"X-CSRF-Token": "wrong"})
        self.assertEqual(blocked.status_code, 403)
        self.save(client)
        self.post.assert_not_called()
        bad = client.post(
            "/api/v1/llm/test", json={"expected_revision": 1, "consent": False}
        )
        self.assertEqual(bad.status_code, 422)
        result = client.post(
            "/api/v1/llm/test", json={"expected_revision": 1, "consent": True}
        )
        self.assertEqual(result.json()["status"], "passed")
        view = client.get(SETTINGS)
        self.assertNotIn(KEY, view.text + result.text)
        self.assertNotIn("authorization_file", view.text)
        self.assertEqual(self.post.call_count, 1)

    def test_default_service_off_does_not_initialize_configuration(self):
        client = self.app_client(default=True)
        self.assertIsInstance(client.app.state.llm_settings, LLMSettingsService)
        self.authenticate(client)
        self.assertEqual(client.get(SETTINGS).json()["status"], "disabled")
        self.assertFalse(self.config.exists())
        self.post.assert_not_called()

    def test_new_enqueue_captures_hot_immutable_private_profile(self):
        client = self.app_client()
        self.authenticate(client)
        self.save(client)
        _, _, _, old, path = self.enqueue(client)
        original = path.read_bytes()
        self.assertEqual((old.policy.model, old.policy.api_key), ("synthetic-v1", KEY))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.save(client, expected_revision=1, model="synthetic-v2")
        _, _, _, new, _ = self.enqueue(client)
        self.assertEqual(new.policy.model, "synthetic-v2")
        self.assertNotEqual(old.job_id, new.job_id)
        self.assertEqual(path.read_bytes(), original)
        self.runner.start.assert_not_called()
        self.post.assert_not_called()

    def test_resume_preserves_same_context_policy_and_spent_quota(self):
        client = self.app_client()
        self.authenticate(client)
        self.save(client)
        project, job, old_spec, old, path = self.enqueue(client)
        result, budget = self.resolve(old)
        self.assertEqual((result.status, budget.calls), ("resolved", 1))
        original = path.read_bytes()
        self.assertEqual(client.post(f"/api/v1/jobs/{job}/cancel").status_code, 200)
        self.save(client, expected_revision=1, response_mode="json-object")
        _, _, spec, resumed, _ = self.enqueue(client, project=project, resume=job)
        self.assertEqual(spec.llm_context_id, old_spec.llm_context_id)
        self.assertEqual(resumed.policy.response_mode, "json-schema")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(list(path.parent.glob("*.policy.json"))), 1)
        self.assertEqual(
            EvidenceCallBudget(resumed.job_id, ledger=resumed.ledger).calls, 1
        )

    def test_off_and_withdrawn_consent_revoke_existing_snapshot_requests(self):
        client = self.app_client()
        self.authenticate(client)
        self.save(client)
        _, _, _, context, path = self.enqueue(client)
        original = path.read_bytes()
        self.save(client, expected_revision=1, mode="off", data_consent=True)
        self.assertEqual(self.resolve(context)[0].reason, "authorization_revoked")
        self.save(client, expected_revision=2)
        authority = self.config / "llm.local.yaml"
        data = yaml.safe_load(authority.read_text())
        data["evidence_resolution"]["data_consent"] = False
        authority.write_text(
            yaml.safe_dump(data)
        )  # Synthetic operator revocation only.
        self.assertEqual(self.resolve(context)[0].reason, "authorization_revoked")
        self.assertEqual(path.read_bytes(), original)
        self.post.assert_not_called()

    def test_response_after_revocation_is_not_promoted(self):
        client = self.app_client()
        self.authenticate(client)
        self.save(client)
        _, _, _, context, _ = self.enqueue(client)

        def revoked(*args, **kwargs):
            self.save(client, expected_revision=1, mode="off", data_consent=False)
            return self.wire(*args, **kwargs)

        self.post.side_effect = revoked
        result, budget = self.resolve(context)
        self.assertEqual(
            (result.status, result.reason), ("disabled", "authorization_revoked")
        )
        self.assertEqual((self.post.call_count, budget.calls), (1, 1))

    def test_missing_or_corrupt_budget_resume_is_rejected_without_new_quota(self):
        client = self.app_client()
        self.authenticate(client)
        self.save(client)
        project, job, _, context, path = self.enqueue(client)
        client.post(f"/api/v1/jobs/{job}/cancel")
        original = path.read_bytes()
        context.ledger.unlink()  # Only this test's generated private ledger.
        result = client.post(
            f"/api/v1/projects/{project}/jobs", json={"resume_job_id": job}
        )
        self.assertEqual(
            (result.status_code, result.json()["error"]["code"]),
            (409, "llm_configuration"),
        )
        self.assertFalse(context.ledger.exists())
        self.assertEqual(path.read_bytes(), original)
        context.ledger.write_text('{"calls":"corrupt"}')
        context.ledger.chmod(0o600)
        corrupt = context.ledger.read_bytes()
        result = client.post(
            f"/api/v1/projects/{project}/jobs", json={"resume_job_id": job}
        )
        self.assertEqual(result.status_code, 409)
        self.assertEqual(context.ledger.read_bytes(), corrupt)
        self.post.assert_not_called()

    def test_explicit_job_renewal_uses_saved_credential_without_starting_or_resetting(
        self,
    ):
        client = self.app_client()
        self.authenticate(client)
        self.save(client)
        project, job, _, context, path = self.enqueue(client)
        self.post.side_effect = APIRequestError(
            APIProblem("authentication_failed", 401)
        )
        result, budget = self.resolve(context)
        self.assertEqual(result.reason, "authentication_failed")
        client.post(f"/api/v1/jobs/{job}/cancel")
        original = path.read_bytes()
        self.save(client, expected_revision=1, api_key="rotated-synthetic-key")
        state = client.get(f"/api/v1/jobs/{job}").json()
        self.assertTrue(state["llm_recovery"]["can_reauthorize"])
        self.assertEqual(state["llm_recovery"]["remaining_calls"], 7)
        renewed = client.post(
            f"/api/v1/jobs/{job}/llm-authorization",
            json={"expected_revision": 2, "consent": True},
        )
        self.assertEqual(renewed.status_code, 200, renewed.text)
        self.assertEqual(renewed.json()["status"], "cancelled")
        self.assertEqual(renewed.json()["llm_recovery"]["status"], "ready")
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(budget.calls, 1)
        self.assertEqual(path.read_bytes(), original)
        self.assertNotIn("rotated-synthetic-key", renewed.text)
        self.runner.start.assert_not_called()
        self.post.side_effect = self.wire
        _, _, resumed_spec, resumed, _ = self.enqueue(
            client, project=project, resume=job
        )
        self.assertEqual(resumed_spec.llm_context_id, context.job_id)
        after, after_budget = self.resolve(resumed)
        self.assertEqual(after.status, "resolved")
        self.assertEqual(after_budget.calls, 2)

    def test_job_renewal_requires_idle_visibility_consent_and_current_revision(self):
        client = self.app_client()
        self.authenticate(client)
        self.save(client)
        _, job, _, _, path = self.enqueue(client)
        self.assertEqual(
            client.post(
                f"/api/v1/jobs/{job}/llm-authorization",
                json={"expected_revision": 1, "consent": True},
            ).status_code,
            409,
        )
        client.post(f"/api/v1/jobs/{job}/cancel")
        self.save(client, expected_revision=1, api_key="rotated-synthetic-key")
        endpoint = f"/api/v1/jobs/{job}/llm-authorization"
        self.assertEqual(
            client.post(
                endpoint, json={"expected_revision": 2, "consent": False}
            ).status_code,
            422,
        )
        self.assertEqual(
            client.post(
                endpoint, json={"expected_revision": 1, "consent": True}
            ).status_code,
            409,
        )
        self.assertEqual(
            client.post(
                endpoint,
                json={"expected_revision": 2, "consent": True},
                headers={"X-CSRF-Token": "wrong"},
            ).status_code,
            403,
        )
        self.assertFalse(
            path.with_name(
                path.name.replace(".policy.json", ".authorization.json")
            ).exists()
        )
        self.post.assert_not_called()

    def test_job_renewal_cannot_switch_the_original_semantic_profile(self):
        client = self.app_client()
        self.authenticate(client)
        self.save(client)
        _, job, _, context, path = self.enqueue(client)
        client.post(f"/api/v1/jobs/{job}/cancel")
        self.save(
            client,
            expected_revision=1,
            model="different-model",
            api_key="different-key",
        )
        state = client.get(f"/api/v1/jobs/{job}").json()
        self.assertFalse(state["llm_recovery"]["can_reauthorize"])
        self.assertEqual(
            client.post(
                f"/api/v1/jobs/{job}/llm-authorization",
                json={"expected_revision": 2, "consent": True},
            ).status_code,
            409,
        )
        self.assertEqual(read_context(path).policy.model, context.policy.model)
        self.post.assert_not_called()
