"""Opt-in candidate resolution against exact evidence; all HTTP is controlled."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import requests

from patent_sar_extractor.integrations.llm import client
from patent_sar_extractor.integrations.llm import config as llm_config
from patent_sar_extractor.integrations.llm.config import (
    EvidenceResolutionConfig,
    get_evidence_resolution_config,
)
from patent_sar_extractor.integrations.llm.evidence_resolution import (
    EvidenceCallBudget,
    EvidenceCandidate,
    EvidenceObservation,
    EvidenceRequest,
    resolve_evidence,
)


class EvidenceResolutionTests(unittest.TestCase):
    def setUp(self):
        self.config = EvidenceResolutionConfig(
            mode="quality",
            data_consent=True,
            endpoint="https://one.invalid/v1",
            api_key="private-test-key",
            model="controlled-model",
        )
        self.request = EvidenceRequest(
            job_id="controlled-job",
            original_sha256="a" * 64,
            task="heading-owner",
            trigger="quality",
            observations=(
                EvidenceObservation("text-1", "text", "EXAMPLES"),
                EvidenceObservation("region-1", "region", "Original heading region"),
            ),
            candidates=(
                EvidenceCandidate("heading-1", "body heading", ("text-1", "region-1")),
            ),
        )
        self.budget = EvidenceCallBudget(self.request.job_id)
        self.enterContext(
            patch.object(
                client.requests,
                "post",
                side_effect=AssertionError("unit test must not use direct HTTP/DNS"),
            )
        )
        self.post = self.enterContext(patch.object(client, "bounded_post"))
        self.response(
            '{"candidates":[{"candidate_id":"heading-1","observation_ids":["text-1"]}]}'
        )

    def response(self, content, *, finish_reason="stop"):
        packet = {
            "choices": [
                {"message": {"content": content}, "finish_reason": finish_reason}
            ]
        }
        response = json.dumps(packet).encode()
        self.post.return_value = response
        self.post.side_effect = None
        return response

    def resolve(self, *, config=None, request=None):
        return resolve_evidence(
            request or self.request, self.budget, config=config or self.config
        )

    def test_default_off_never_reads_cache_or_calls_network(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "patent_sar_extractor.integrations.llm.config._load_yaml_config",
                return_value={},
            ),
            patch.object(client, "_cached") as cache,
        ):
            result = resolve_evidence(self.request, self.budget)
        self.assertEqual(result.status, "disabled")
        self.assertEqual(result.outcome, "skipped")
        self.post.assert_not_called()
        cache.assert_not_called()
        self.assertEqual(self.budget.calls, 0)

    def test_missing_explicit_data_consent_is_zero_disclosure(self):
        result = self.resolve(config=replace(self.config, data_consent=False))
        self.assertEqual(result.status, "disabled")
        self.assertEqual(result.reason, "data_consent_required")
        self.post.assert_not_called()

    def test_invalid_or_missing_configuration_never_calls_network(self):
        for changes in (
            {"endpoint": ""},
            {"endpoint": "http://remote.invalid"},
            {"endpoint": "https://user:secret@one.invalid"},
            {"model": ""},
            {"api_key": ""},
            {"timeout": 46},
            {"retries": 2},
            {"max_calls": 9},
            {"max_input_chars": 0},
            {"max_output_chars": 0},
            {"max_tokens": 4097},
            {"max_tokens": True},
            {"mode": "always"},
        ):
            with self.subTest(changes=tuple(changes)):
                result = self.resolve(config=replace(self.config, **changes))
                self.assertNotEqual(result.status, "resolved")
        self.post.assert_not_called()

    def test_optional_policy_config_has_its_own_bounded_defaults(self):
        yaml = {
            "shared": {
                "endpoint": "https://one.invalid/v1",
                "api_key": "controlled-key",
                "model": "controlled",
                "timeout": 180,
            },
            "evidence_resolution": {"mode": "on-error", "data_consent": True},
        }
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "patent_sar_extractor.integrations.llm.config._load_yaml_config",
                return_value=yaml,
            ),
        ):
            config = get_evidence_resolution_config()
        self.assertEqual(
            (config.mode, config.timeout, config.retries, config.max_calls),
            ("on-error", 30, 0, 8),
        )
        self.assertTrue(config.data_consent)
        self.assertNotIn("controlled-key", repr(config))

    def test_invalid_policy_option_is_not_silently_coerced_to_enabled_default(self):
        with (
            patch.dict(
                os.environ,
                {
                    "PATENTSAR_LLM_RESOLUTION_MODE": "quality",
                    "PATENTSAR_LLM_RESOLUTION_DATA_CONSENT": "yes",
                },
                clear=True,
            ),
            patch(
                "patent_sar_extractor.integrations.llm.config._load_yaml_config",
                return_value={},
            ),
        ):
            result = resolve_evidence(self.request, self.budget)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.outcome, "failed")
        self.post.assert_not_called()

    def test_enabled_policy_without_provider_config_cannot_use_hardcoded_fallbacks(
        self,
    ):
        with (
            patch.dict(os.environ, {"LLM_API_KEY": "private-test-key"}, clear=True),
            patch(
                "patent_sar_extractor.integrations.llm.config._load_yaml_config",
                return_value={
                    "evidence_resolution": {"mode": "quality", "data_consent": True}
                },
            ),
        ):
            result = resolve_evidence(self.request, self.budget)
        self.assertEqual(result.status, "unavailable")
        self.post.assert_not_called()

    def test_request_deadline_prevents_a_second_attempt_after_elapsed_timeout(self):
        self.post.side_effect = requests.Timeout()
        with patch.object(client.time, "monotonic", side_effect=[0, 0, 31]):
            result = self.resolve(config=replace(self.config, retries=1))
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(self.post.call_count, 1)

    def test_only_approved_candidate_tasks_are_supported(self):
        for task in ("heading-owner", "table-header", "column-mapping"):
            with self.subTest(task=task):
                result = self.resolve(request=replace(self.request, task=task))
                self.assertEqual(result.status, "resolved")
                self.assertEqual(result.outcome, "proposed")
                self.assertEqual(result.candidates[0].candidate_id, "heading-1")
                self.assertEqual(result.candidates[0].observation_ids, ("text-1",))
        self.assertEqual(self.post.call_count, 3)

    def test_strict_request_carries_original_and_exact_observation_ids(self):
        self.assertEqual(self.resolve().status, "resolved")
        payload = self.post.call_args.kwargs["json"]
        supplied = json.loads(payload["messages"][1]["content"])
        self.assertNotIn("job_id", supplied)
        self.assertNotIn("trigger", supplied)
        self.assertNotIn("fault_kind", supplied)
        self.assertEqual(supplied["protocol_version"], 1)
        self.assertEqual(supplied["original_sha256"], self.request.original_sha256)
        self.assertEqual(supplied["observations"][0]["observation_id"], "text-1")
        self.assertEqual(supplied["observations"][1]["observation_id"], "region-1")
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual(payload["max_tokens"], self.config.max_tokens)
        self.assertLessEqual(self.post.call_args.kwargs["timeout"], 45)
        self.assertEqual(self.budget.calls, 1)

    def test_on_error_mode_does_not_resolve_quality_only_requests(self):
        result = self.resolve(config=replace(self.config, mode="on-error"))
        self.assertEqual(result.status, "disabled")
        self.post.assert_not_called()
        result = self.resolve(
            config=replace(self.config, mode="on-error"),
            request=replace(self.request, trigger="on-error"),
        )
        self.assertEqual(result.status, "resolved")

    def test_infrastructure_and_memory_faults_never_escalate_to_llm(self):
        for kind in ("infrastructure", "memory"):
            with self.subTest(kind=kind):
                result = self.resolve(
                    request=replace(self.request, fault_kind=kind, trigger="on-error")
                )
                self.assertEqual(result.status, "unavailable")
        self.post.assert_not_called()

    def test_character_budget_rejects_whole_request_instead_of_truncating_evidence(
        self,
    ):
        result = self.resolve(config=replace(self.config, max_input_chars=100))
        self.assertEqual(
            (result.status, result.reason), ("unavailable", "input_budget")
        )
        self.assertEqual(self.budget.calls, 0)
        self.post.assert_not_called()

    def test_output_token_and_character_limits_are_enforced(self):
        result = self.resolve(
            config=replace(self.config, max_tokens=12, max_output_chars=8)
        )
        self.assertNotEqual(result.status, "resolved")
        self.assertEqual(self.post.call_args.kwargs["json"]["max_tokens"], 12)
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(result.candidates, ())

    def test_invalid_source_identity_task_or_candidate_refs_fail_before_network(self):
        for changes in (
            {"original_sha256": "unknown"},
            {"job_id": "another-job"},
            {"task": "smiles"},
            {"observations": self.request.observations * 2},
            {"candidates": (EvidenceCandidate("heading-1", "heading", ("foreign",)),)},
            {"observations": ()},
            {"candidates": ()},
        ):
            with self.subTest(changes=tuple(changes)):
                self.assertNotEqual(
                    self.resolve(request=replace(self.request, **changes)).status,
                    "resolved",
                )
        self.post.assert_not_called()

    def test_unknown_candidates_or_observations_cannot_be_invented(self):
        for content in (
            '{"candidates":[{"candidate_id":"new-compound","observation_ids":["text-1"]}]}',
            '{"candidates":[{"candidate_id":"heading-1","observation_ids":["foreign-text"]}]}',
            '{"candidates":[{"candidate_id":"heading-1","observation_ids":[]}]}',
        ):
            with self.subTest(content=content):
                self.response(content)
                result = self.resolve()
                self.assertEqual(result.status, "invalid_response")
                self.assertEqual(result.candidates, ())

    def test_citations_must_belong_to_that_supplied_candidate(self):
        request = replace(
            self.request,
            candidates=(EvidenceCandidate("heading-1", "heading", ("text-1",)),),
        )
        self.response(
            '{"candidates":[{"candidate_id":"heading-1","observation_ids":["region-1"]}]}'
        )
        self.assertEqual(self.resolve(request=request).status, "invalid_response")

    def test_scientific_values_ids_smiles_stereo_or_acceptance_are_forbidden_fields(
        self,
    ):
        for field in (
            "compound_id",
            "activity_value",
            "smiles",
            "stereo",
            "acceptance",
        ):
            with self.subTest(field=field):
                content = {
                    "candidates": [
                        {
                            "candidate_id": "heading-1",
                            "observation_ids": ["text-1"],
                            field: "invented",
                        }
                    ]
                }
                self.response(json.dumps(content))
                self.assertEqual(self.resolve().status, "invalid_response")

    def test_malformed_fenced_duplicate_or_nonfinite_json_is_not_salvaged(self):
        for content in (
            "not JSON",
            '```json\n{"candidates":[]}\n```',
            "[]",
            '{"candidates":[],"candidates":[]}',
            '{"candidates":NaN}',
            '{"candidates":[],"explanation":"unrequested"}',
        ):
            with self.subTest(content=content):
                self.response(content)
                self.assertEqual(self.resolve().status, "invalid_response")
        self.assertEqual(self.post.call_count, 6)

    def test_duplicate_output_choices_and_citations_are_rejected(self):
        choice = {"candidate_id": "heading-1", "observation_ids": ["text-1"]}
        for choices in (
            [choice, choice],
            [{**choice, "observation_ids": ["text-1", "text-1"]}],
        ):
            self.response(json.dumps({"candidates": choices}))
            self.assertEqual(self.resolve().status, "invalid_response")

    def test_empty_selection_is_explicit_abstention_not_generated_data(self):
        self.response('{"candidates":[]}')
        result = self.resolve()
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.outcome, "unresolved")
        self.assertEqual(asdict(result)["outcome"], "unresolved")

    def test_truncated_provider_output_is_unavailable_even_if_json_looks_valid(self):
        self.response('{"candidates":[]}', finish_reason="length")
        self.assertEqual(self.resolve().status, "unavailable")

    def test_retry_consumes_same_job_budget_and_never_exceeds_eight_attempts(self):
        self.post.side_effect = requests.Timeout(
            "private-test-key must never be logged"
        )
        config = replace(self.config, retries=1)
        with self.assertLogs(client.logger, level="WARNING") as logs:
            for _ in range(5):
                self.assertNotEqual(self.resolve(config=config).status, "resolved")
        self.assertEqual(self.post.call_count, 8)
        self.assertEqual(self.budget.calls, 8)
        self.assertNotIn("private-test-key", " ".join(logs.output))
        self.assertEqual(self.resolve(config=config).status, "budget_exhausted")
        self.assertEqual(self.resolve(config=config).outcome, "skipped")
        self.assertEqual(self.post.call_count, 8)

    def test_default_has_no_retry_and_request_exceptions_do_not_leak_secrets(self):
        self.post.side_effect = requests.RequestException("private-test-key")
        with self.assertLogs(client.logger, level="WARNING") as logs:
            result = self.resolve()
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(self.post.call_count, 1)
        self.assertNotIn("private-test-key", " ".join(logs.output))

    def test_serial_busy_budget_is_bounded_without_parallel_network(self):
        self.budget._serial.acquire()
        try:
            result = self.resolve()
        finally:
            self.budget._serial.release()
        self.assertEqual((result.status, result.reason), ("unavailable", "serial_busy"))
        self.post.assert_not_called()

    def test_resumed_attempt_reuses_source_cache_without_disclosing_job_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(
                self.config, cache_path=str(Path(temporary) / "llm.sqlite")
            )
            first = self.resolve(config=config)
            resumed = replace(self.request, job_id="resumed-job", trigger="on-error")
            resumed_budget = EvidenceCallBudget(resumed.job_id)
            second = resolve_evidence(resumed, resumed_budget, config=config)
        self.assertEqual((first.outcome, second.outcome), ("proposed", "proposed"))
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual((self.budget.calls, resumed_budget.calls), (1, 0))
        self.assertNotIn(
            self.request.job_id,
            self.post.call_args.kwargs["json"]["messages"][1]["content"],
        )

    def test_malformed_yaml_config_is_failed_not_silently_disabled_and_redacts_keys(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "llm.yaml"
            path.write_text("shared:\n  api_key: [private-test-key\n")
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(llm_config, "LLM_CONFIG_PATHS", (path,)),
            ):
                llm_config._load_yaml_config.cache_clear()
                try:
                    with self.assertLogs(llm_config.logger, level="WARNING") as logs:
                        result = resolve_evidence(self.request, self.budget)
                finally:
                    llm_config._load_yaml_config.cache_clear()
        self.assertEqual(
            (result.outcome, result.reason), ("failed", "invalid_configuration")
        )
        self.assertNotIn("private-test-key", " ".join(logs.output))
        self.post.assert_not_called()

    def test_cache_identity_binds_source_observations_provider_model_and_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(
                self.config, cache_path=str(Path(temporary) / "llm.sqlite")
            )
            self.assertEqual(self.resolve(config=config).status, "resolved")
            self.assertEqual(self.resolve(config=config).status, "resolved")
            self.assertEqual(self.post.call_count, 1)
            self.assertEqual(
                self.resolve(
                    config=replace(config, endpoint="https://two.invalid/v1")
                ).status,
                "resolved",
            )
            self.assertEqual(
                self.resolve(config=replace(config, model="another-model")).status,
                "resolved",
            )
            self.assertEqual(
                self.resolve(
                    config=config,
                    request=replace(self.request, original_sha256="b" * 64),
                ).status,
                "resolved",
            )
            changed = replace(
                self.request.observations[0], text="Changed supplied observation"
            )
            self.assertEqual(
                self.resolve(
                    config=config,
                    request=replace(
                        self.request,
                        observations=(changed, self.request.observations[1]),
                    ),
                ).status,
                "resolved",
            )
            self.assertEqual(
                self.resolve(config=replace(config, max_tokens=512)).status, "resolved"
            )
            changed_region = replace(
                self.request.observations[1], observation_id="region-2"
            )
            changed_candidate = replace(
                self.request.candidates[0], observation_ids=("text-1", "region-2")
            )
            self.assertEqual(
                self.resolve(
                    config=config,
                    request=replace(
                        self.request,
                        observations=(self.request.observations[0], changed_region),
                        candidates=(changed_candidate,),
                    ),
                ).status,
                "resolved",
            )
            self.assertEqual(
                self.resolve(
                    config=config, request=replace(self.request, task="column-mapping")
                ).status,
                "resolved",
            )
            self.assertEqual(self.post.call_count, 8)
            self.assertNotEqual(
                client._cache_key([], "m", 0, response_format={"type": "json_object"}),
                client._cache_key([], "m", 0),
            )
            disabled = self.resolve(config=replace(config, data_consent=False))
            self.assertEqual(disabled.status, "disabled")
            self.assertEqual(self.post.call_count, 8)

    def test_oversized_injected_transport_body_is_rejected(self):
        self.post.return_value = b"x" * 1000000
        self.assertEqual(self.resolve().status, "unavailable")
        self.assertEqual(self.post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
