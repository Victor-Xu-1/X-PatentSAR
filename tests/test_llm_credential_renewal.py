"""Real private config/context/ledger; renewal never starts an API or a task."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from patent_sar_extractor.integrations.llm.config import snapshot_disclosure_allowed
from patent_sar_extractor.integrations.llm.credential_authorization import (
    renew_authorization,
)
from patent_sar_extractor.integrations.llm.evidence_resolution import EvidenceCallBudget
from patent_sar_extractor.integrations.llm.job_context import (
    create_context,
    read_context,
)
from patent_sar_extractor.integrations.llm.job_health import gate, record_fault
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.llm_models import LLMSettingsRequest
from patent_sar_extractor.web.llm_settings import LLMSettingsService


class CredentialRenewalTests(unittest.TestCase):
    def setup_context(self, root):
        service = LLMSettingsService(root / "config")
        body = LLMSettingsRequest(
            expected_revision=0,
            endpoint="https://api.example.org/v1",
            model="controlled",
            mode="on-error",
            data_consent=True,
            api_key="first-synthetic-key",
        )
        service.save_settings(body)
        path = create_context(root / "workspace", "a" * 32, "b" * 64, service.policy())
        return service, body, path

    def test_new_gui_snapshot_has_reference_not_duplicate_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            service, _, path = self.setup_context(Path(temporary))
            self.assertNotIn("first-synthetic-key", path.read_text())
            context = read_context(path)
            self.assertTrue(snapshot_disclosure_allowed(context.policy))
            self.assertEqual(context.policy.api_key, service.policy().api_key)

    def test_key_rotation_needs_explicit_grant_and_keeps_original_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, body, path = self.setup_context(root)
            original = path.read_bytes()
            context = read_context(path)
            budget = EvidenceCallBudget(context.job_id, ledger=context.ledger)
            budget.acquire()
            budget.reserve(8)
            budget.release()
            record_fault(
                context.ledger,
                context.job_id,
                SimpleNamespace(
                    reason="authentication_failed",
                    http_status=401,
                    retryable=False,
                    retry_after_seconds=None,
                ),
            )
            self.assertEqual(
                gate(context.ledger, context.job_id)[0], "authentication_failed"
            )
            service.save_settings(
                body.model_copy(
                    update={"expected_revision": 1, "api_key": "second-synthetic-key"}
                )
            )
            revoked = read_context(path)
            self.assertFalse(snapshot_disclosure_allowed(revoked.policy))
            with patch(
                "patent_sar_extractor.integrations.llm.client.bounded_post"
            ) as api:
                service.renew_job(revoked, 2)
            api.assert_not_called()
            renewed = read_context(path)
            self.assertTrue(snapshot_disclosure_allowed(renewed.policy))
            self.assertEqual(renewed.policy.api_key, "second-synthetic-key")
            self.assertEqual(
                EvidenceCallBudget(context.job_id, ledger=context.ledger).calls, 1
            )
            self.assertIsNone(gate(context.ledger, context.job_id))
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn(
                "second-synthetic-key",
                (renewed.root / (renewed.job_id + ".authorization.json")).read_text(),
            )

    def test_changed_semantics_and_stale_revision_cannot_renew(self):
        with tempfile.TemporaryDirectory() as temporary:
            service, body, path = self.setup_context(Path(temporary))
            context = read_context(path)
            with self.assertRaises(WebError):
                service.renew_job(context, 0)
            service.save_settings(
                body.model_copy(
                    update={
                        "expected_revision": 1,
                        "model": "different",
                        "api_key": "different-key",
                    }
                )
            )
            with self.assertRaises(WebError):
                service.renew_job(context, 2)
            self.assertFalse(
                (context.root / (context.job_id + ".authorization.json")).exists()
            )

    def test_busy_quota_lock_and_off_policy_reject_renewal(self):
        with tempfile.TemporaryDirectory() as temporary:
            service, _, path = self.setup_context(Path(temporary))
            context = read_context(path)
            budget = EvidenceCallBudget(context.job_id, ledger=context.ledger)
            budget.acquire()
            try:
                with self.assertRaises(WebError):
                    service.renew_job(context, 1)
            finally:
                budget.release()
            with self.assertRaises(ValueError):
                renew_authorization(
                    replace(context, policy=replace(context.policy, mode="off")),
                    service.policy(),
                    1,
                )
