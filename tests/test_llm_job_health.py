"""One logical API job survives process/consumer changes without retry storms."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.integrations.llm import client
from patent_sar_extractor.integrations.llm.api_failures import (
    APIProblem,
    APIRequestError,
)
from patent_sar_extractor.integrations.llm.config import EvidenceResolutionConfig
from patent_sar_extractor.integrations.llm.evidence_resolution import (
    EvidenceCallBudget,
    EvidenceCandidate,
    EvidenceObservation,
    EvidenceRequest,
    resolve_evidence,
)
from patent_sar_extractor.integrations.llm.job_context import (
    create_context,
    read_context,
)
from patent_sar_extractor.integrations.llm.job_health import read_state, state_path
from patent_sar_extractor.integrations.llm.private_state import write_private


class APIJobHealthTests(unittest.TestCase):
    def context(self, root):
        policy = EvidenceResolutionConfig(
            mode="on-error",
            data_consent=True,
            endpoint="https://api.example.org/v1",
            model="controlled",
            api_key="synthetic-only",
        )
        return read_context(create_context(root, "a" * 32, "b" * 64, policy))

    def request(self, context):
        return EvidenceRequest(
            context.job_id,
            context.original_sha256,
            "table-header",
            (EvidenceObservation("header", "text", "Example ID"),),
            (EvidenceCandidate("column", "Printed ID", ("header",)),),
            "on-error",
        )

    def resolve(self, context, request=None):
        budget = EvidenceCallBudget(context.job_id, ledger=context.ledger)
        return resolve_evidence(
            request or self.request(context),
            budget,
            config=context.policy,
            require_complete_refs=True,
            max_selected=1,
        )

    def response(self):
        content = json.dumps(
            {"candidates": [{"candidate_id": "column", "observation_ids": ["header"]}]}
        )
        return json.dumps(
            {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        ).encode()

    def test_authentication_fault_blocks_other_consumers_without_spending_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = self.context(Path(temporary))
            with patch.object(
                client,
                "bounded_post",
                side_effect=APIRequestError(APIProblem("authentication_failed", 401)),
            ) as api:
                first = self.resolve(context)
                second = self.resolve(
                    context, replace(self.request(context), task="qa-findings")
                )
            self.assertEqual(
                (first.reason, second.reason),
                ("authentication_failed", "authentication_failed"),
            )
            self.assertEqual(api.call_count, 1)
            self.assertEqual(second.calls_used, 1)
            self.assertNotIn("synthetic-only", state_path(context.ledger).read_text())

    def test_rate_limit_wait_survives_new_budget_then_explicit_retry_can_recover(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = self.context(Path(temporary))
            with patch.object(
                client,
                "bounded_post",
                side_effect=APIRequestError(APIProblem("rate_limited", 429, True, 7)),
            ) as api:
                first = self.resolve(context)
                later = self.resolve(context)
            self.assertEqual(api.call_count, 1)
            self.assertEqual(
                (first.reason, later.reason), ("rate_limited", "rate_limited")
            )
            fault = read_state(context.ledger, context.job_id)
            with (
                patch.dict(os.environ, {"PATENTSAR_API_ATTEMPT_ID": "e" * 32}),
                patch(
                    "patent_sar_extractor.integrations.llm.job_health.time.time",
                    return_value=fault["retry_at"] + 1,
                ),
                patch.object(
                    client, "bounded_post", return_value=self.response()
                ) as recovered,
            ):
                result = self.resolve(context)
            self.assertEqual(result.status, "resolved")
            self.assertEqual(result.calls_used, 2)
            recovered.assert_called_once()

    def test_invalid_cached_selection_is_removed_before_valid_current_answer(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = self.context(Path(temporary))
            with (
                patch.object(
                    client,
                    "_cached",
                    return_value='{"candidates":[{"candidate_id":"invented","observation_ids":["header"]}]}',
                ),
                patch.object(client, "_cache_discard") as discard,
                patch.object(
                    client, "bounded_post", return_value=self.response()
                ) as api,
            ):
                result = self.resolve(context)
            self.assertEqual(result.status, "resolved")
            discard.assert_called_once()
            api.assert_called_once()
            self.assertIsNone(read_state(context.ledger, context.job_id))

    def test_corrupt_or_foreign_health_cannot_reset_or_enable_a_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = self.context(Path(temporary))
            write_private(
                state_path(context.ledger), {"schema": {}, "job_id": "foreign"}
            )
            with patch.object(client, "bounded_post") as api:
                result = self.resolve(context)
            self.assertEqual(result.status, "unavailable")
            self.assertEqual(result.calls_used, 0)
            api.assert_not_called()

    def test_same_running_attempt_does_not_restart_api_after_cooldown_expires(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = self.context(Path(temporary))
            with (
                patch.dict(os.environ, {"PATENTSAR_API_ATTEMPT_ID": "c" * 32}),
                patch.object(
                    client,
                    "bounded_post",
                    side_effect=APIRequestError(
                        APIProblem("rate_limited", 429, True, 1)
                    ),
                ) as api,
            ):
                self.resolve(context)
                health = read_state(context.ledger, context.job_id)
                with patch(
                    "patent_sar_extractor.integrations.llm.job_health.time.time",
                    return_value=health["retry_at"] + 100,
                ):
                    again = self.resolve(context)
                self.assertEqual(again.reason, "rate_limited")
                api.assert_called_once()

    def test_standalone_invocation_without_explicit_id_keeps_its_circuit_closed(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(os.environ, {}, clear=True),
        ):
            context = self.context(Path(temporary))
            with patch.object(
                client,
                "bounded_post",
                side_effect=APIRequestError(APIProblem("rate_limited", 429, True, 1)),
            ) as api:
                self.resolve(context)
                health = read_state(context.ledger, context.job_id)
                with patch(
                    "patent_sar_extractor.integrations.llm.job_health.time.time",
                    return_value=health["retry_at"] + 100,
                ):
                    again = self.resolve(context)
                self.assertEqual(again.reason, "rate_limited")
                self.assertEqual(again.calls_used, 1)
                api.assert_called_once()
                self.assertRegex(health["attempt_id"], r"^[a-f0-9]{32}$")
            with (
                patch.dict(os.environ, {"PATENTSAR_API_ATTEMPT_ID": "d" * 32}),
                patch(
                    "patent_sar_extractor.integrations.llm.job_health.time.time",
                    return_value=health["retry_at"] + 100,
                ),
                patch.object(
                    client, "bounded_post", return_value=self.response()
                ) as api,
            ):
                resumed = self.resolve(context)
                self.assertEqual(resumed.status, "resolved")
                self.assertEqual(resumed.calls_used, 2)
                api.assert_called_once()
