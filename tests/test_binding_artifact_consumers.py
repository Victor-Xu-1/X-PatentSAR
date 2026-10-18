"""Native original -> shared writer -> current downstream admission, without ML."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from patent_sar_extractor.application.binding_policy import (
    _binding_acceptance_errors,
    _load_bindings_from_json,
    _load_reusable_bindings,
)
from patent_sar_extractor.application.header_resolution import make_header_resolver
from patent_sar_extractor.application.stage_cache import (
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.artifact_catalog import MARKER
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.core.ocsr.run_smiles import (
    load_bindings,
    validate_strict_binding_input,
)
from patent_sar_extractor.integrations.llm.config import EvidenceResolutionConfig
from patent_sar_extractor.web.attempts import CheckpointCopy
from patent_sar_extractor.web.compound_catalog import read_compound_catalog
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.processes import RunSpec
from tests.test_heading_ruled_binding import run_original


class BindingArtifactConsumerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="binding-artifact-consumers-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.result, self.payload = run_original(
            self.root, raster=False, image_directory=self.root / "structures"
        )
        self.path = Path(self.result["output_files"]["json"])
        # Prove these checks traverse the new persisted transport, not only an
        # in-memory writer return or a plain JSON compatibility path.
        self.assertIn(MARKER, json.loads(self.path.read_text()))

    def test_current_native_worker_and_safe_web_read_the_same_proved_source(self):
        payload, rows = _load_bindings_from_json(str(self.path))
        self.assertEqual(payload, self.payload)
        self.assertEqual(_binding_acceptance_errors(payload), [])
        self.assertEqual(load_bindings(str(self.path)), rows)
        self.assertEqual(validate_strict_binding_input(str(self.path), rows), [])
        plan = recognition_inputs(payload)
        self.assertEqual(plan.formal, rows)
        self.assertEqual(plan.supplemental, [])
        self.assertEqual(plan.reprints, [])
        web = SafeFiles(self.path.parent).json(self.path.name, optional=False)
        entries, _ = read_compound_catalog(web, web["final_bindings"])
        self.assertEqual([entry["cpd"] for entry in entries], ["Compound 82A"])

    def test_current_shared_and_legacy_plain_caches_replay_without_mutating_evidence(
        self,
    ):
        fingerprint = _step_fingerprint(
            "bind", pdf_path=str(self.root / "original.pdf")
        )
        plain = self.path.with_name("legacy-plain.json")
        write_json_atomic(plain, self.payload)
        for path in (self.path, plain):
            with self.subTest(shared=path == self.path):
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                _write_step_manifest(str(path), fingerprint)
                self.assertEqual(
                    _load_reusable_bindings(str(path), fingerprint), self.payload
                )
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_valid_transport_cannot_qualify_changed_scientific_ownership(self):
        changed = copy.deepcopy(self.payload)
        changed["final_bindings"][0]["cpd"] = "Compound 83B"
        path = self.path.with_name("changed-original-owner.json")
        write_json_atomic(path, changed, shared=True)
        web = SafeFiles(path.parent).json(path.name, optional=False)
        self.assertEqual(web, changed)  # Transport integrity alone is not science.
        self.assertTrue(_binding_acceptance_errors(web))
        # The worker's composed admission checks the complete original plan,
        # not only the earlier per-row quality/status check.
        with self.assertRaises(ValueError):
            recognition_inputs(web)
        entries, _ = read_compound_catalog(web, web["final_bindings"])
        self.assertEqual([entry["cpd"] for entry in entries], ["Compound 82A"])

        changed["compound_catalog"]["entries"][0]["original_heading_evidence"][
            "heading_observation"
        ]["original_pdf_sha256"] = "b" * 64
        write_json_atomic(path, changed, shared=True)
        web = SafeFiles(path.parent).json(path.name, optional=False)
        with self.assertRaises(ValueError):
            _binding_acceptance_errors(web)
        with self.assertRaises(ValueError):
            recognition_inputs(web)
        with self.assertRaises((ValueError, WebError)):
            read_compound_catalog(web, web["final_bindings"])

    def test_real_source_checkpoint_relocation_is_readable_by_the_native_cache(self):
        source = self.root / "structure_bindings/bindings.json"
        write_json_atomic(source, self.payload, shared=True)
        pdf = self.root / "original.pdf"
        fingerprint = _step_fingerprint("bind", pdf_path=str(pdf))
        _write_step_manifest(str(source), fingerprint)
        original = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        spec = RunSpec(
            "a" * 32,
            "b" * 32,
            str(pdf),
            str(self.root),
            "CONTROL",
            hashlib.sha256(pdf.read_bytes()).hexdigest(),
        )
        transport = CheckpointCopy(self.root, self.root / "next-attempt")
        verified = transport.verify("bind", spec)
        self.assertIsNotNone(verified)
        transport.checkpoint(verified)
        target = transport.target / "structure_bindings/bindings.json"
        self.assertIn(MARKER, json.loads(target.read_text()))
        current = _load_reusable_bindings(str(target), fingerprint)
        self.assertIsNotNone(current)
        binding = current["final_bindings"][0]
        self.assertEqual(binding["cpd"], "Compound 82A")
        self.assertEqual(
            binding["original_heading_evidence"],
            self.payload["final_bindings"][0]["original_heading_evidence"],
        )
        copied_image = Path(binding["image_path"])
        self.assertTrue(copied_image.is_relative_to(transport.target))
        self.assertEqual(
            copied_image.read_bytes(),
            (self.root / "structures/structure.png").read_bytes(),
        )
        self.assertEqual(
            {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in original},
            original,
        )

    def test_activity_header_catalog_uses_shared_reader_without_any_api_call(self):
        policy = EvidenceResolutionConfig(
            mode="on-error",
            data_consent=True,
            endpoint="https://never-called.invalid/v1",
            model="controlled",
            api_key="controlled-not-a-real-key",
        )
        with (
            patch(
                "patent_sar_extractor.application.header_resolution.get_evidence_resolution_config",
                return_value=policy,
            ),
            patch(
                "patent_sar_extractor.application.header_resolution.context_for_run",
                return_value=SimpleNamespace(job_id="a" * 32, ledger=None),
            ),
            patch(
                "patent_sar_extractor.integrations.llm.client.bounded_post",
                side_effect=AssertionError(
                    "No model request is part of this reader check"
                ),
            ) as api,
        ):
            resolver = make_header_resolver(
                str(self.root / "original.pdf"),
                str(self.root / "activity"),
                str(self.path),
            )
        self.assertTrue(callable(resolver))
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
