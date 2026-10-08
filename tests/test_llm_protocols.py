"""User-selected third-party wire protocols use one bounded client, no SDKs."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from patent_sar_extractor.integrations.llm.client import llm_chat
from patent_sar_extractor.integrations.llm.protocol_adapters import (
    build_request,
    response_text,
)

KEY = "controlled-private-test-key"
SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "test",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["nonce"],
            "properties": {"nonce": {"type": "string", "enum": ["proof"]}},
        },
    },
}
MESSAGES = [
    {"role": "system", "content": "Return strict JSON only."},
    {"role": "user", "content": "nonce proof"},
]


class APIProtocolTests(unittest.TestCase):
    def config(self, protocol, response_mode="json-schema"):
        return {
            "protocol": protocol,
            "response_mode": response_mode,
            "endpoint": "https://api.example.org/v1",
            "api_key": KEY,
            "model": "controlled",
            "cache_path": "",
        }

    def test_three_protocols_preserve_schema_model_and_header_only_credentials(self):
        for protocol, suffix, header in (
            ("openai-compatible", "/chat/completions", "Authorization"),
            ("anthropic", "/messages", "x-api-key"),
            ("gemini", "/models/controlled:generateContent", "x-goog-api-key"),
        ):
            with self.subTest(protocol=protocol):
                wire = build_request(
                    self.config(protocol), MESSAGES, "controlled", 0, 128, SCHEMA
                )
                self.assertTrue(wire.url.endswith(suffix))
                self.assertIn(KEY, wire.headers[header])
                self.assertNotIn(KEY, wire.url + json.dumps(wire.payload))
                self.assertIn("proof", json.dumps(wire.payload))

    def test_compat_response_modes_are_explicit_without_fallback(self):
        for mode, expected in (
            ("json-schema", "json_schema"),
            ("json-object", "json_object"),
            ("prompt-only", None),
        ):
            wire = build_request(
                self.config("openai-compatible", mode),
                MESSAGES,
                "controlled",
                0,
                128,
                SCHEMA,
            )
            self.assertEqual(
                wire.payload.get("response_format", {}).get("type"), expected
            )
        with self.assertRaises(ValueError):
            build_request(
                self.config("local-inference"), MESSAGES, "controlled", 0, 128, SCHEMA
            )

    def test_all_provider_envelopes_use_exact_same_client_transport(self):
        packets = {
            "openai-compatible": {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"nonce":"proof"}'},
                    }
                ]
            },
            "anthropic": {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"nonce":"proof"}'}],
            },
            "gemini": {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": '{"nonce":"proof"}'}]},
                    }
                ]
            },
        }
        for protocol, packet in packets.items():
            with (
                self.subTest(protocol=protocol),
                patch(
                    "patent_sar_extractor.integrations.llm.client.bounded_post",
                    return_value=json.dumps(packet).encode(),
                ) as carrier,
            ):
                self.assertEqual(
                    llm_chat(
                        MESSAGES,
                        config=self.config(protocol),
                        cache=False,
                        max_tokens=128,
                        response_format=SCHEMA,
                    ),
                    '{"nonce":"proof"}',
                )
                self.assertEqual(carrier.call_count, 1)
                self.assertTrue(carrier.call_args.kwargs["require_public"])

    def test_truncated_tools_thinking_and_refusal_are_not_salvaged(self):
        for protocol, packet in (
            (
                "openai-compatible",
                {
                    "choices": [
                        {"finish_reason": "length", "message": {"content": "{}"}}
                    ]
                },
            ),
            (
                "anthropic",
                {
                    "stop_reason": "tool_use",
                    "content": [{"type": "tool_use", "input": {}}],
                },
            ),
            (
                "gemini",
                {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {"parts": [{"text": "{}", "thought": True}]},
                        }
                    ]
                },
            ),
        ):
            with self.subTest(protocol=protocol), self.assertRaises(ValueError):
                response_text(packet, protocol)

    def test_native_model_cannot_inject_url_and_exact_wire_input_is_bounded(self):
        with self.assertRaises(ValueError):
            build_request(
                self.config("gemini"), MESSAGES, "../metadata", 0, 128, SCHEMA
            )
        with patch(
            "patent_sar_extractor.integrations.llm.client.bounded_post"
        ) as carrier:
            with self.assertRaises(ValueError):
                llm_chat(
                    MESSAGES,
                    config=self.config("openai-compatible", "prompt-only"),
                    cache=False,
                    response_format=SCHEMA,
                    max_request_chars=10,
                )
        carrier.assert_not_called()
