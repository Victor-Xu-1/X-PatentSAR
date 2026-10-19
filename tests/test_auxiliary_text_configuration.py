"""Producer ownership is explicit; reads and refused producers cannot load/close it."""

import tempfile
import unittest
from contextvars import Context
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.core.text_ocr import configuration as configured


class Reader:
    def __init__(self, *paths):
        self.closed = 0

    def close(self):
        self.closed += 1


class AuxiliaryConfigurationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.settings = {
            "PATENTSAR_TEXT_OCR_MODE": "on_demand",
            "PATENTSAR_TEXT_OCR_MODEL_DIR": str(self.root / "models"),
        }
        self.stack = []
        for target, replacement in (
            ("configured_model_environment", lambda: self.settings),
            ("get_python", lambda role: "/verified/ocr/bin/python"),
            ("state_dir", lambda: self.root),
        ):
            self.stack.append(patch.object(configured, target, replacement))
        self.stack.append(
            patch(
                "patent_sar_extractor.core.text_ocr.runtime.AuxiliaryTextRuntime",
                Reader,
            )
        )
        for item in self.stack:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(configured.release_auxiliary_text_runtime)

    def test_read_only_access_does_not_even_read_configuration(self):
        with patch.object(
            configured,
            "configured_model_environment",
            side_effect=AssertionError("not a producer"),
        ):
            self.assertIsNone(configured.get_auxiliary_text_runtime())

    def test_default_off_cache_identity_never_reads_models_or_creates_runtime(self):
        self.settings.clear()
        with patch(
            "patent_sar_extractor.core.text_ocr.identity.model_files",
            side_effect=AssertionError("no model access"),
        ):
            self.assertEqual(configured.text_ocr_policy_identity(), {"mode": "off"})

    def test_enabled_cache_identity_retains_exact_selection_without_inference(self):
        with patch(
            "patent_sar_extractor.core.text_ocr.identity.model_files",
            return_value=[("fixed-model", "a" * 64)],
        ) as verify:
            identity = configured.text_ocr_policy_identity()
        verify.assert_called_once()
        self.assertEqual(identity["mode"], "on_demand")
        self.assertEqual(identity["python"], "/verified/ocr/bin/python")
        self.assertEqual(identity["models"], [("fixed-model", "a" * 64)])
        self.assertIsNone(configured._OWNER)

    def test_nested_owner_is_reused_and_closed_at_outer_boundary(self):
        with configured.auxiliary_text_phase():
            owner = configured.get_auxiliary_text_runtime()
            with configured.auxiliary_text_phase():
                self.assertIs(owner, configured.get_auxiliary_text_runtime())
            self.assertEqual(owner.closed, 0)
        self.assertEqual(owner.closed, 1)
        self.assertIsNone(configured.get_auxiliary_text_runtime())

    def test_binding_owns_and_releases_its_optional_reader_on_source_failure(self):
        from patent_sar_extractor.core.structure_binder import bind

        owners = []

        def failing_source(*args):
            owners.append(configured.get_auxiliary_text_runtime())
            raise ValueError("controlled original-source failure")

        with (
            patch(
                "patent_sar_extractor.core.structure_binder.load_binding_input",
                side_effect=failing_source,
            ),
            self.assertRaisesRegex(ValueError, "controlled original"),
        ):
            bind("unused.pdf", {}, "unused-output")
        self.assertEqual(len(owners), 1)
        self.assertIsNotNone(owners[0])
        self.assertEqual(owners[0].closed, 1)
        self.assertIsNone(configured.get_auxiliary_text_runtime())

    def test_refused_concurrent_phase_never_closes_first_owner(self):
        def competing():
            with configured.auxiliary_text_phase():
                configured.get_auxiliary_text_runtime()

        with configured.auxiliary_text_phase():
            owner = configured.get_auxiliary_text_runtime()
            with self.assertRaisesRegex(RuntimeError, "owner/configuration"):
                Context().run(competing)
            self.assertIs(owner, configured.get_auxiliary_text_runtime())
            self.assertEqual(owner.closed, 0)
        self.assertEqual(owner.closed, 1)

    def test_active_configuration_changes_are_not_silently_applied(self):
        with configured.auxiliary_text_phase():
            owner = configured.get_auxiliary_text_runtime()
            self.settings["PATENTSAR_TEXT_OCR_MODEL_DIR"] = str(self.root / "other")
            with self.assertRaises(RuntimeError):
                configured.get_auxiliary_text_runtime()
            self.assertEqual(owner.closed, 0)
        self.assertEqual(owner.closed, 1)

    def test_invalid_mode_and_shared_workspace_are_refused(self):
        with configured.auxiliary_text_phase():
            self.settings["PATENTSAR_TEXT_OCR_MODE"] = "guess"
            with self.assertRaises(ValueError):
                configured.get_auxiliary_text_runtime()
            self.settings["PATENTSAR_TEXT_OCR_MODE"] = "off"
            self.assertIsNone(configured.get_auxiliary_text_runtime())
            self.settings["PATENTSAR_TEXT_OCR_MODE"] = "on_demand"
            workspace = self.root / "text-ocr-transient"
            workspace.mkdir(mode=0o755)
            with self.assertRaisesRegex(ValueError, "private"):
                configured.get_auxiliary_text_runtime()
