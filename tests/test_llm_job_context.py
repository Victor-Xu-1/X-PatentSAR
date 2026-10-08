"""Persistent API settings/quota across processes and safe interruption/resume."""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.integrations.llm.config import (
    EvidenceResolutionConfig,
    get_evidence_resolution_config,
)
from patent_sar_extractor.integrations.llm.evidence_resolution import EvidenceCallBudget
from patent_sar_extractor.integrations.llm.job_context import (
    create_context,
    read_context,
)
from patent_sar_extractor.integrations.llm.private_state import write_private
from patent_sar_extractor.web.processes import CLIProcessRunner, RunSpec


class JobAPIContextTests(unittest.TestCase):
    def test_snapshot_is_private_immutable_and_original_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = EvidenceResolutionConfig(
                mode="quality",
                data_consent=True,
                endpoint="https://api.example.org/v1",
                api_key="private-controlled",
                model="old",
            )
            path = create_context(root, "a" * 32, "b" * 64, policy)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                create_context(root, "a" * 32, "b" * 64, replace(policy, model="new"))
            with patch.dict(
                os.environ,
                {
                    "PATENTSAR_LLM_CONTEXT": str(path),
                    "LLM_MODEL": "new",
                    "PATENTSAR_LLM_RESOLUTION_MODE": "off",
                },
            ):
                self.assertEqual(get_evidence_resolution_config().model, "old")
            self.assertNotIn("private-controlled", repr(read_context(path)))

    def test_quota_is_spent_before_http_and_is_not_reset_by_new_instance(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = read_context(
                create_context(
                    Path(temporary),
                    "a" * 32,
                    "b" * 64,
                    EvidenceResolutionConfig(max_calls=2),
                )
            )
            first = EvidenceCallBudget(context.job_id, 2, ledger=context.ledger)
            self.assertTrue(first.acquire())
            self.assertTrue(first.reserve(2))
            competing = EvidenceCallBudget(context.job_id, 2, ledger=context.ledger)
            self.assertFalse(competing.acquire())
            first.release()
            resumed = EvidenceCallBudget(context.job_id, 2, ledger=context.ledger)
            self.assertTrue(resumed.acquire())
            self.assertEqual(resumed.calls, 1)
            self.assertTrue(resumed.reserve(2))
            self.assertFalse(resumed.reserve(2))
            resumed.release()

    def test_corrupt_budget_and_symlink_do_not_reset_or_leak(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = read_context(
                create_context(root, "a" * 32, "b" * 64, EvidenceResolutionConfig())
            )
            write_private(context.ledger, {"job_id": "foreign", "limit": 8, "calls": 0})
            with self.assertRaises(ValueError):
                _ = EvidenceCallBudget(context.job_id, ledger=context.ledger).calls
            link = root / "linked.policy.json"
            link.symlink_to(root / "llm" / ("a" * 32 + ".policy.json"))
            with self.assertRaises((OSError, ValueError)):
                read_context(link)

    def test_off_snapshot_does_not_duplicate_stored_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = create_context(
                Path(temporary),
                "a" * 32,
                "b" * 64,
                EvidenceResolutionConfig(api_key="not-to-copy"),
            )
            self.assertNotIn("not-to-copy", path.read_text())

    def test_missing_ledger_cannot_be_resumed_with_fresh_quota(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = create_context(
                Path(temporary), "a" * 32, "b" * 64, EvidenceResolutionConfig()
            )
            context = read_context(path)
            context.ledger.unlink()  # Deliberate loss of this isolated controlled record.
            with self.assertRaises((OSError, ValueError)):
                read_context(path)
            with self.assertRaises((OSError, ValueError)):
                _ = EvidenceCallBudget(context.job_id, ledger=context.ledger).calls

    def test_semantic_cache_identity_excludes_keys_and_distinguishes_modes_models(self):
        from patent_sar_extractor.application.stage_activity import (
            evidence_policy_identity,
        )

        first = EvidenceResolutionConfig(
            mode="quality",
            data_consent=True,
            endpoint="https://api.example.org/v1",
            model="first",
            api_key="key1",
        )
        with patch(
            "patent_sar_extractor.application.stage_activity.get_evidence_resolution_config",
            return_value=first,
        ):
            identity = evidence_policy_identity()
        self.assertNotIn("key1", str(identity))
        with patch(
            "patent_sar_extractor.application.stage_activity.get_evidence_resolution_config",
            return_value=replace(first, api_key="key2"),
        ):
            self.assertEqual(evidence_policy_identity(), identity)
        with patch(
            "patent_sar_extractor.application.stage_activity.get_evidence_resolution_config",
            return_value=replace(first, model="second"),
        ):
            self.assertNotEqual(evidence_policy_identity(), identity)
        with patch(
            "patent_sar_extractor.application.stage_activity.get_evidence_resolution_config",
            return_value=replace(first, mode="off"),
        ):
            self.assertEqual(evidence_policy_identity(), {"mode": "off"})

    def test_clearing_consent_provider_or_credential_revokes_frozen_gui_profile(self):
        import yaml
        from patent_sar_extractor.integrations.llm.config import (
            snapshot_disclosure_allowed,
        )

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "llm.local.yaml"
            provider = {
                "endpoint": "https://api.example.org/v1",
                "model": "controlled",
                "api_key": "controlled",
                "protocol": "openai-compatible",
            }
            enabled = {"mode": "on-error", "data_consent": True}
            policy = EvidenceResolutionConfig(
                **provider, **enabled, authorization_file=str(path)
            )

            def save(current, settings):
                path.write_text(
                    yaml.safe_dump(
                        {
                            "llm": current,
                            "evidence_resolution": settings,
                            "api_settings": {"revision": 1},
                        }
                    )
                )
                path.chmod(0o600)

            save(provider, enabled)
            self.assertTrue(snapshot_disclosure_allowed(policy))
            for current, settings in (
                (provider, {"mode": "off", "data_consent": True}),
                (provider, {"mode": "on-error", "data_consent": False}),
                ({**provider, "api_key": ""}, enabled),
                ({**provider, "model": "changed"}, enabled),
            ):
                save(current, settings)
                self.assertFalse(snapshot_disclosure_allowed(policy))
            path.unlink()
            self.assertFalse(snapshot_disclosure_allowed(policy))

    def test_owned_cli_only_receives_current_private_snapshot_not_parent_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            create_context(root, "a" * 32, "b" * 64, EvidenceResolutionConfig())
            spec = RunSpec(
                "a" * 32,
                "p",
                "/original.pdf",
                str(root / "runs"),
                "",
                "b" * 64,
                workspace_root=str(root),
                llm_context_id="a" * 32,
            )
            with patch.dict(
                os.environ,
                {"LLM_API_KEY": "parent-secret", "VLM_API_KEY": "parent-secret"},
            ):
                env = CLIProcessRunner().environment(spec)
            self.assertNotIn("LLM_API_KEY", env)
            self.assertNotIn("VLM_API_KEY", env)
            self.assertNotIn("--skip-advisory-qa", CLIProcessRunner().command(spec))
            self.assertEqual(
                read_context(env["PATENTSAR_LLM_CONTEXT"]).original_sha256, "b" * 64
            )
