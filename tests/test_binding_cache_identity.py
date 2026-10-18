"""Historical derived binding/classification caches keep independent identity."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.application.binding_policy import _load_reusable_bindings
from patent_sar_extractor.application.stage_cache import (
    _fingerprint_matches,
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.artifact_nodes import MAX_ARTIFACT_BYTES
from patent_sar_extractor.contracts import ruleset_ref


class BindingCacheIdentityTests(unittest.TestCase):
    def test_oversized_legacy_output_is_not_reused_or_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.json"
            with path.open("wb") as stream:
                stream.seek(MAX_ARTIFACT_BYTES)
                stream.write(b" ")
            with patch(
                "patent_sar_extractor.application.binding_policy._fingerprint_matches",
                side_effect=AssertionError(
                    "Oversized output must not be parsed or retagged"
                ),
            ):
                self.assertIsNone(_load_reusable_bindings(str(path), {}))
            self.assertEqual(path.stat().st_size, MAX_ARTIFACT_BYTES + 1)

    def test_previous_ruleset_binding_cache_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "input.pdf"
            pdf.write_bytes(b"cache-identity-only")
            artifact = Path(directory) / "bindings.json"
            artifact.write_text("{}", encoding="utf-8")
            current = _step_fingerprint("bind", pdf_path=str(pdf))
            previous = {**current, "ruleset": {**ruleset_ref(), "version": "2.0.0"}}
            _write_step_manifest(str(artifact), previous)
            self.assertFalse(_fingerprint_matches(str(artifact), current))
            _write_step_manifest(str(artifact), current)
            self.assertTrue(_fingerprint_matches(str(artifact), current))

    def test_classification_cache_manifest_requires_current_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "input.pdf"
            pdf.write_bytes(b"cache-identity-only")
            artifact = root / "classification.json"
            artifact.write_text("{}", encoding="utf-8")
            current = _step_fingerprint("classify", pdf_path=str(pdf))
            _write_step_manifest(str(artifact), current)
            manifest_path = Path(str(artifact) + ".manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["ruleset"]["version"] = "2.0.0"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertFalse(_fingerprint_matches(str(artifact), current))
            _write_step_manifest(str(artifact), current)
            self.assertTrue(_fingerprint_matches(str(artifact), current))
