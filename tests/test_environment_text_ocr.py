"""Auxiliary OCR follows the existing single transactional environment manager."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from patent_sar_extractor.core.env_runner import captured_runtime_environment
from patent_sar_extractor.core.text_ocr.identity import recipe
from patent_sar_extractor.web.analysis_runtime import AnalysisSettings
from patent_sar_extractor.web.environment_config import EnvironmentConfig
from patent_sar_extractor.web.environment_inspection import (
    InspectionContext,
    inspect_components,
)
from patent_sar_extractor.web.environment_specs import (
    component_catalog,
    recipe_path,
    resolved_components,
)


class TextOCREnvironmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = EnvironmentConfig(self.root)
        env = patch.dict(
            os.environ, {"PATENTSAR_CONFIG_DIR": str(self.root)}, clear=True
        )
        env.start()
        self.addCleanup(env.stop)

    def test_one_managed_plan_includes_only_fixed_dependencies(self):
        self.assertEqual(
            resolved_components(["text-ocr-models"]),
            ["installer", "text-ocr", "text-ocr-models"],
        )
        cards = {c["id"]: c for c in component_catalog()}
        self.assertFalse(cards["text-ocr"]["required"])
        self.assertEqual(
            cards["text-ocr-models"]["download_bytes"],
            sum(m["size"] for m in recipe()["models"]),
        )
        lock = recipe_path("text-ocr-requirements.txt").read_text()
        requirements = [
            line for line in lock.splitlines() if line and not line.startswith("#")
        ]
        self.assertEqual(len(requirements), 75)
        self.assertTrue(all(" --hash=sha256:" in line for line in requirements))
        self.assertNotIn("transformers==", lock)
        self.assertNotIn("nvidia-", lock)

    def test_no_main_interpreter_fallback_is_presented_as_an_ocr_runtime(self):
        with patch.dict(os.environ, {"PATENTSAR_PYTHON": "/existing/main/bin/python"}):
            bindings = self.config.bindings(AnalysisSettings())
        self.assertIsNone(bindings["text-ocr"])
        self.assertIsNone(bindings["text-ocr-models"])

    def test_verified_pair_is_enabled_atomically_and_snapshot_carries_selection(self):
        selected = {
            "text-ocr": "/verified/text-ocr/bin/python",
            "text-ocr-models": "/verified/text-ocr/models",
        }
        self.config.publish("a" * 32, self.config.fingerprint(), selected)
        saved = yaml.safe_load((self.root / "env_paths.local.yaml").read_text())
        self.assertEqual(saved["paddleocr_mode"], "on_demand")
        self.assertEqual(saved["paddleocr"], selected["text-ocr"])
        captured = captured_runtime_environment()
        self.assertEqual(captured["PADDLEOCR_PYTHON"], selected["text-ocr"])
        self.assertEqual(captured["PATENTSAR_TEXT_OCR_MODE"], "on_demand")
        self.assertEqual(
            captured["PATENTSAR_TEXT_OCR_MODEL_DIR"], selected["text-ocr-models"]
        )

    def test_runtime_only_publication_cannot_enable_unchecked_models(self):
        self.config.publish(
            "a" * 32,
            self.config.fingerprint(),
            {
                "text-ocr": "/verified/text-ocr/bin/python",
                "text-ocr-models": "/verified/text-ocr/models",
            },
        )
        self.config.publish(
            "b" * 32,
            self.config.fingerprint(),
            {"text-ocr": "/new/text-ocr/bin/python"},
        )
        saved = yaml.safe_load((self.root / "env_paths.local.yaml").read_text())
        self.assertEqual(saved["paddleocr_mode"], "off")
        self.assertEqual(saved["paddleocr_models"], "/verified/text-ocr/models")
        self.assertEqual(len(list((self.root / ".environment-backups").iterdir())), 2)

    def test_inspection_context_preserves_exact_selection(self):
        bindings = {
            "text-ocr": "/verified/text-ocr/bin/python",
            "text-ocr-models": "/verified/text-ocr/models",
        }
        captured = InspectionContext.from_bindings(bindings).bindings()
        self.assertTrue(all(captured[k] == value for k, value in bindings.items()))


@unittest.skipUnless(
    os.environ.get("PATENTSAR_TEST_TEXT_OCR_PYTHON")
    and os.environ.get("PATENTSAR_TEST_TEXT_OCR_MODELS"),
    "Explicit isolated ordinary-text runtime/model required",
)
class NativeManagedTextOCRTests(unittest.TestCase):
    def test_existing_isolated_runtime_and_weights_are_really_checked_offline(self):
        context = InspectionContext(
            text_ocr=Path(os.environ["PATENTSAR_TEST_TEXT_OCR_PYTHON"]),
            text_ocr_models=Path(os.environ["PATENTSAR_TEST_TEXT_OCR_MODELS"]),
        )
        with tempfile.TemporaryDirectory() as temporary:
            reports = inspect_components(
                ["text-ocr", "text-ocr-models"], context, op_dir=Path(temporary)
            )
        for report in reports:
            self.assertEqual(report.status, "ready", report.model_dump())
            self.assertTrue(all(c.ok for c in report.checks))
            self.assertEqual(report.detected_version, "3.7.0")
