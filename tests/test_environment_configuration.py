from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from patent_sar_extractor.core.env_runner import (
    captured_runtime_environment,
    get_python,
)
from patent_sar_extractor.web.analysis_runtime import AnalysisSettings
from patent_sar_extractor.web.environment_config import EnvironmentConfig
from patent_sar_extractor.web.errors import WebError


class EnvironmentConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = EnvironmentConfig(self.root)
        self.path = self.root / "env_paths.local.yaml"
        self.override = patch.dict(
            os.environ, {"PATENTSAR_CONFIG_DIR": str(self.root)}, clear=True
        )
        self.override.start()
        self.addCleanup(self.override.stop)

    def write(self, value):
        self.path.write_text(yaml.safe_dump(value))
        self.path.chmod(0o600)

    def test_malformed_and_non_mapping_configuration_fail_with_safe_errors(self):
        for value in ("[]", "false", "base: ["):
            self.path.write_text(value)
            self.path.chmod(0o600)
            with self.subTest(value=value), self.assertRaises(WebError) as context:
                self.config.loaded()
            self.assertEqual(context.exception.code, "environment_configuration")
            self.assertNotIn(value, context.exception.message)
            self.assertEqual(self.path.read_text(), value)

    def test_changed_configuration_is_visible_and_running_snapshot_stays_frozen(self):
        self.write(
            {
                "base": "/existing/base/bin/python",
                "decimer": "/existing/decimer/bin/python",
                "decimer_models": "/existing/models",
            }
        )
        captured = captured_runtime_environment()
        self.write(
            {
                "base": "/verified/base/bin/python",
                "decimer": "/verified/decimer/bin/python",
                "decimer_models": "/verified/models",
            }
        )
        self.assertEqual(get_python("base"), "/verified/base/bin/python")
        self.assertEqual(captured["PATENTSAR_BASE_PYTHON"], "/existing/base/bin/python")
        self.assertEqual(captured["DECIMER_PYTHON"], "/existing/decimer/bin/python")
        self.assertEqual(captured["PYSTOW_HOME"], "/existing/models")
        with patch.dict(os.environ, captured):
            self.assertEqual(get_python("base"), "/existing/base/bin/python")
            self.assertEqual(
                AnalysisSettings.from_environment().pystow_home,
                Path("/existing/models"),
            )

    def test_analysis_and_cli_share_configuration_with_explicit_overrides(self):
        self.write(
            {
                "admet": "/verified/admet/bin/python",
                "admet_models": "/verified/admet-models",
                "decimer": "/verified/decimer/bin/python",
                "decimer_models": "/verified/models",
            }
        )
        settings = AnalysisSettings.from_environment()
        self.assertEqual(settings.admet_python, Path("/verified/admet/bin/python"))
        self.assertEqual(settings.admet_model_dir, Path("/verified/admet-models"))
        self.assertEqual(settings.decimer_python, Path("/verified/decimer/bin/python"))
        with patch.dict(
            os.environ,
            {
                "PATENTSAR_ADMET_PYTHON": "/operator/admet/bin/python",
                "DECIMER_PYTHON": "/operator/decimer/bin/python",
            },
        ):
            settings = AnalysisSettings.from_environment()
            self.assertEqual(settings.admet_python, Path("/operator/admet/bin/python"))
            self.assertEqual(
                settings.decimer_python, Path("/operator/decimer/bin/python")
            )

    def test_atomic_publication_preserves_operator_fields_and_backup(self):
        self.write({"custom_operator_setting": "preserve", "base": "/existing/python"})
        before = self.path.read_bytes()
        operation = "a" * 32
        result = self.config.publish(
            operation,
            self.config.fingerprint(),
            {
                "base": "/verified/base/bin/python",
                "admet": "/verified/admet/bin/python",
                "admet-models": "/verified/models",
            },
        )
        self.assertEqual(result.admet_python, Path("/verified/admet/bin/python"))
        saved = yaml.safe_load(self.path.read_text())
        self.assertEqual(saved["custom_operator_setting"], "preserve")
        self.assertEqual(saved["base"], saved["smiles_engine"])
        self.assertEqual(saved["base"], saved["pymupdf"])
        self.assertEqual(saved["_managed_environment_operation"], operation)
        self.assertEqual(
            (self.root / ".environment-backups" / (operation + ".yaml")).read_bytes(),
            before,
        )
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_concurrent_operator_change_is_not_overwritten(self):
        self.write({"base": "/existing/python"})
        fingerprint = self.config.fingerprint()
        self.write({"base": "/user/new/python", "custom": "preserve"})
        before = self.path.read_bytes()
        with self.assertRaisesRegex(WebError, "changed"):
            self.config.publish("b" * 32, fingerprint, {"base": "/verified/python"})
        self.assertEqual(self.path.read_bytes(), before)

    def test_symlink_configuration_is_not_read_or_replaced(self):
        original = self.root / "private.yaml"
        original.write_text("base: /user/python")
        self.path.symlink_to(original)
        with self.assertRaises(WebError):
            self.config.fingerprint()
        self.assertEqual(original.read_text(), "base: /user/python")


if __name__ == "__main__":
    unittest.main()
