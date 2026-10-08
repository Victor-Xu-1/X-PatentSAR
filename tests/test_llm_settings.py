"""Private synthetic YAML and real API/client parsing; no DNS or paid calls."""

from __future__ import annotations

import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from patent_sar_extractor.integrations.llm import client
from patent_sar_extractor.web import llm_settings as settings
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.llm_models import LLMSettingsRequest, LLMTestRequest
from patent_sar_extractor.web.llm_settings_storage import LLMSettingsStorage

KEY = "synthetic-private-key-never-real"


class LLMSettingsTests(unittest.TestCase):
    def patched(self, obj, name, **options):
        return self.enterContext(patch.object(obj, name, **options))

    def setUp(self):
        root = Path(os.getenv("PATENTSAR_WEB_TEST_ROOT", "/srv/wsl/tmp/llm-tests"))
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = tempfile.TemporaryDirectory(prefix="llm-", dir=root)
        self.addCleanup(temporary.cleanup)
        self.root, self.directory = Path(temporary.name), Path(temporary.name) / "cfg"
        default = self.root / "default.yaml"
        default.write_text("{}\n")
        self.service = settings.LLMSettingsService(self.directory)
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.patched(settings.paths, "config_files", return_value=(default, default))
        self.dns = self.patched(socket, "getaddrinfo", side_effect=AssertionError())
        self.patched(client.requests, "post", side_effect=AssertionError())
        self.post = self.patched(client, "bounded_post", side_effect=self.echo)
        self.chat = self.patched(settings, "llm_chat", wraps=client.llm_chat)

    @staticmethod
    def packet(content):
        choice = {"message": {"content": content}, "finish_reason": "stop"}
        return json.dumps({"choices": [choice]}).encode()

    def echo(self, *args, **kwargs):
        payload = kwargs["json"]
        if "contents" in payload:
            parts = [{"text": payload["contents"][0]["parts"][0]["text"]}]
            candidate = {"finishReason": "STOP", "content": {"parts": parts}}
            return json.dumps({"candidates": [candidate]}).encode()
        content = payload["messages"][-1]["content"]
        if "output_config" in payload:
            parts = [{"type": "text", "text": content}]
            return json.dumps({"stop_reason": "end_turn", "content": parts}).encode()
        return self.packet(content)

    @staticmethod
    def body(**changes):
        fields = {
            "expected_revision": 0,
            "endpoint": "https://api.example.com/v1",
            "model": "synthetic",
            "mode": "off",
            "data_consent": False,
        }
        return LLMSettingsRequest(**(fields | changes))

    def ready(self, **changes):
        fields = {"mode": "quality", "data_consent": True, "api_key": KEY}
        return self.save(**(fields | changes))

    def save(self, service=None, **changes):
        return (service or self.service).save_settings(self.body(**changes))

    def seed(self, data):
        self.directory.mkdir(mode=0o700, exist_ok=True)
        path = self.directory / "llm.local.yaml"
        path.write_text(yaml.safe_dump(data))
        path.chmod(0o600)
        return path

    def rejected(self, service=None, **changes):
        with self.assertRaises(WebError) as error:
            self.save(service, **changes)
        self.assertNotIn(KEY, json.dumps(error.exception.payload()))
        return error.exception.code

    def probe(self, revision=1):
        return self.service.test_connection(
            LLMTestRequest(expected_revision=revision, consent=True)
        )

    def test_off_read_save_and_policy_have_no_network_or_install_side_effects(self):
        self.assertEqual(self.service.get_settings().status, "disabled")
        self.assertEqual(self.service.policy().mode, "off")
        self.assertFalse(self.directory.exists())
        self.rejected(expected_revision=1)
        self.assertFalse(self.directory.exists())
        self.save(api_key=KEY)
        with self.assertRaises(WebError):
            self.probe()
        self.chat.assert_not_called()

    def test_preservation_permissions_redaction_and_hot_snapshot(self):
        extra = {"shared": {"api_key": "legacy-key"}, "vlm": {}, "custom": [1]}
        path = self.seed(extra)
        saved = self.ready()
        data = yaml.safe_load(path.read_text())
        self.assertEqual({key: data[key] for key in extra}, extra)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        data["llm"]["model"] = "hot-model"
        self.seed(data)
        self.assertEqual(self.service.policy().model, "hot-model")
        self.assertNotIn(KEY, saved.model_dump_json() + repr(self.body(api_key=KEY)))

    def test_cas_and_endpoint_model_protocol_key_boundaries(self):
        self.seed({"shared": {"api_key": "legacy-key"}})
        self.ready()
        path = self.directory / "llm.local.yaml"
        original = yaml.safe_load(path.read_text())
        self.rejected()
        for field, value in (
            ("model", "other"),
            ("endpoint", "https://other.example.com"),
            ("protocol", "anthropic"),
        ):
            self.seed(original)
            before = path.read_bytes()
            change = {field: value, "expected_revision": 1}
            self.assertEqual(self.rejected(**change), "llm_key_replacement_required")
            self.assertEqual(path.read_bytes(), before)
            self.ready(**change)  # Explicit re-entry of exactly the same KEY.
        self.seed(original)
        view = self.save(expected_revision=1, response_mode="prompt-only")
        self.assertEqual(view.response_mode, "prompt-only")
        cleared = self.save(expected_revision=2, protocol="gemini", api_key="")
        self.assertFalse(cleared.key_configured)
        self.assertEqual(self.service.policy().api_key, "")

    def test_endpoint_and_enabled_validation_require_explicit_consent(self):
        urls = [
            "http://api.example.com",
            "https://10.0.0.1",
            "https://user:secret@api.example.com",
            "https://api.example.com/?key=x",
        ]
        for url in urls:
            self.rejected(endpoint=url, api_key=KEY)
        for change in (
            {},
            {"data_consent": True},
            {"data_consent": True, "api_key": KEY, "model": ""},
        ):
            self.rejected(mode="quality", **change)
        self.chat.assert_not_called()

    def test_env_overrides_lock_edits_and_never_disclose_values(self):
        self.ready()
        path = self.directory / "llm.local.yaml"
        before = path.read_bytes()
        for name in (
            "LLM_API_KEY",
            "LLM_PROTOCOL",
            "LLM_MODEL",
            "LLM_TIMEOUT",
            "PATENTSAR_LLM_RESOLUTION_MODE",
            "PATENTSAR_LLM_RESOLUTION_MAX_TOKENS",
        ):
            with patch.dict(os.environ, {name: "operator-secret"}):
                view = self.service.get_settings()
                self.assertFalse(view.editable)
                self.assertNotIn("operator-secret", view.reason or "")
                self.rejected(expected_revision=1)
        self.assertEqual(path.read_bytes(), before)
        with patch.dict(os.environ, {"LLM_MODEL": " "}):
            self.assertTrue(self.service.get_settings().editable)

    def test_nofollow_regular_private_bounded_yaml_and_safe_errors(self):
        cases = {
            "link": "{}",
            "hard": "{}",
            "fifo": "",
            "mode": "{}",
            "size": "x" * 32769,
            "duplicate": "llm: {}\nllm: {}",
            "alias": "llm: &a {}\nx: *a",
            "parse": f"llm: [{KEY}",
            "metadata": f'api_settings: {{revision: "{KEY}"}}',
        }
        for name, content in cases.items():
            directory = self.root / name
            directory.mkdir(mode=0o700)
            path, target = directory / "llm.local.yaml", self.root / f"t-{name}"
            target.write_text(content)
            target.chmod(0o600)
            if name == "link":
                path.symlink_to(target)
            elif name == "hard":
                os.link(target, path)
            elif name == "fifo":
                os.mkfifo(path, 0o600)
            else:
                path.write_text(content)
                path.chmod(0o644 if name == "mode" else 0o600)
            service = settings.LLMSettingsService(directory)
            self.assertFalse(service.get_settings().editable)
            self.assertNotIn(KEY, service.get_settings().model_dump_json())
            self.rejected(service)
            self.assertEqual(target.read_text(), content)
        alias = self.root / "dir-link"
        alias.symlink_to(self.root, target_is_directory=True)
        self.rejected(settings.LLMSettingsService(alias))
        with patch.dict(os.environ, {"PATENTSAR_CONFIG_DIR": str(alias)}):
            self.assertFalse(settings.LLMSettingsService().get_settings().editable)

    def test_atomic_failure_and_directory_flock_preserve_saved_bytes(self):
        self.ready()
        path = self.directory / "llm.local.yaml"
        before = path.read_bytes()
        with patch(
            "patent_sar_extractor.web.llm_settings_storage.os.replace",
            side_effect=OSError(KEY),
        ):
            self.rejected(expected_revision=1)
        with LLMSettingsStorage(self.directory).transaction():
            self.rejected(
                settings.LLMSettingsService(self.directory), expected_revision=1
            )
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.directory.iterdir()), [path])

    def test_exact_bounded_nonce_probe_profiles_and_reset(self):
        self.ready()
        result = self.probe()
        self.assertEqual((result.status, result.reason), ("passed", "nonce_verified"))
        self.assertEqual(self.service.get_settings().last_test, result)
        options = self.chat.call_args.kwargs
        for key, value in {
            "max_retries": 0,
            "max_tokens": 128,
            "max_response_chars": 2048,
            "max_request_chars": 12000,
            "cache": False,
        }.items():
            self.assertEqual(options[key], value)
        self.assertLessEqual(options["timeout"], 30)
        self.assertTrue(options["response_format"]["json_schema"]["strict"])
        self.assertEqual(options["config"]["protocol"], "openai-compatible")
        self.assertIsNone(self.save(expected_revision=1).last_test)

    def test_invalid_response_errors_changes_and_serial_probe_never_promote(self):
        self.ready()
        for response in (
            "{}",
            "null",
            f'{{"nonce":"{KEY}"}}',
            '{"nonce":"x","nonce":"x"}',
            "bad",
            "x" * 2049,
        ):
            self.post.side_effect = lambda *a, value=response, **kw: self.packet(value)
            self.assertEqual(self.probe().status, "failed")
            self.assertNotIn(KEY, self.service.get_settings().model_dump_json())
        with patch.object(settings, "llm_chat", side_effect=RuntimeError(KEY)):
            self.assertEqual(self.probe().reason, "transport_unavailable")

        def changing(*args, **kwargs):
            with self.assertRaises(WebError):
                self.probe()
            self.save(expected_revision=1)
            return self.echo(*args, **kwargs)

        self.post.reset_mock(side_effect=True)
        self.post.side_effect = changing
        self.assertEqual(self.probe().reason, "settings_changed")
        self.assertIsNone(self.service.get_settings().last_test)
        with self.assertRaises(WebError):
            self.probe(2)
        self.assertEqual(self.post.call_count, 1)

    def test_strict_request_input(self):
        for consent in (False, "true", 1, None):
            with self.assertRaises(ValueError):
                LLMTestRequest(expected_revision=0, consent=consent)
        for key in (None, "bad\nkey", "x" * 4097):
            with self.assertRaises(ValueError):
                self.body(api_key=key)

    def test_profiles_carry_explicitly_reentered_credentials(self):
        self.ready()
        for revision, protocol in ((1, "anthropic"), (2, "gemini")):
            self.ready(expected_revision=revision, protocol=protocol, api_key=KEY)
            self.assertEqual(self.service.policy().protocol, protocol)
            self.assertEqual(self.probe(revision + 1).status, "passed")
            self.assertEqual(self.chat.call_args.kwargs["config"]["protocol"], protocol)
