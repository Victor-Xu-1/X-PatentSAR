"""Internal complete observations retain rejection; standalone/default stays strict."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from patent_sar_extractor.core.ocsr import run_smiles
from patent_sar_extractor.core.ocsr.observation_completion import (
    publish_scientific_findings,
    require_complete_source_results,
    validate_source_observation_mode,
)
from patent_sar_extractor.failures import failure_marker_path
from patent_sar_extractor.resource_admission import ResourceAdmissionError
from patent_sar_extractor.smiles_artifact import smiles_records
from tests.test_source_led_export import run_fixture


class ObservationCompletionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="patentsar-observations-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        run_fixture(self.root)
        self.input_path = self.root / "structure_bindings/bindings.json"
        self.payload = json.loads(self.input_path.read_text())
        self.bindings = self.payload["final_bindings"]
        self.records = smiles_records(
            json.loads((self.root / "smiles/smiles_results.json").read_text())
        )

    def _validate(self, **kwargs):
        options = {"diagnostic": False, "limit": 0, "include_unbound": False, **kwargs}
        validate_source_observation_mode(self.payload, self.bindings, **options)

    def test_current_complete_source_catalog_qualifies_but_is_not_accepted(self):
        original = copy.deepcopy(self.payload)
        self._validate()
        require_complete_source_results(self.bindings, self.records)
        self.assertEqual(self.payload, original)

    def test_diagnostic_limited_and_unbound_modes_cannot_opt_in(self):
        for options in (
            {"diagnostic": True},
            {"limit": 1},
            {"limit": -1},
            {"limit": False},
            {"include_unbound": True},
        ):
            with (
                self.subTest(options=options),
                self.assertRaisesRegex(ValueError, "cannot be diagnostic"),
            ):
                self._validate(**options)

    def test_legacy_mode_cannot_bypass_direct_strict_behavior(self):
        self.payload["execution_mode"] = "production_activity_led"
        with self.assertRaisesRegex(ValueError, "source-led"):
            self._validate()

    def test_wrong_formal_scope_is_rejected(self):
        self.payload["formal_acceptance_scope"] = "other"
        with self.assertRaisesRegex(ValueError, "formal source scope"):
            self._validate()

    def test_partial_binding_or_result_collection_is_not_completion(self):
        with self.assertRaisesRegex(ValueError, "exact proved catalog"):
            validate_source_observation_mode(
                self.payload,
                self.bindings[:1],
                diagnostic=False,
                limit=0,
                include_unbound=False,
            )
        for results in (
            self.records[:1],
            list(reversed(self.records)),
            [self.records[0], self.records[0]],
        ):
            with (
                self.subTest(results=results),
                self.assertRaisesRegex(
                    ValueError, "incomplete, duplicated or misassigned"
                ),
            ):
                require_complete_source_results(self.bindings, results)

    def test_default_scientific_failure_stays_strict_and_writes_the_shared_marker(self):
        errors = ["controlled scientific finding"]
        with self.assertRaisesRegex(RuntimeError, "Strict OCSR output gate failed"):
            publish_scientific_findings(
                str(self.root), errors, continue_on_scientific_errors=False
            )
        marker = json.loads(failure_marker_path(self.root).read_text())
        self.assertEqual(marker["errors"], errors)
        self.assertFalse(marker["deliverables_accepted"])

    def test_continuation_preserves_identical_findings_and_never_accepts_them(self):
        errors = ["controlled scientific finding"]
        publish_scientific_findings(
            str(self.root), errors, continue_on_scientific_errors=True
        )
        marker = json.loads(failure_marker_path(self.root).read_text())
        self.assertEqual(marker["errors"], errors)
        self.assertFalse(marker["deliverables_accepted"])

    def _cli(self, *, continuation=True, extra=(), records=None, infrastructure=False):
        output = self.root / "worker-output" / "smiles.json"
        argv = [
            "run_smiles.py",
            "--input",
            str(self.input_path),
            "--output",
            str(output),
            "--csv-output",
            str(output.with_suffix(".csv")),
            "--cache",
            str(output.with_suffix(".sqlite")),
            "--no-preprocess",
            *extra,
        ]
        if continuation:
            argv.append("--continue-on-scientific-errors")
        converter = Mock()
        converter.cache = None
        converter.engines = {"decimer": SimpleNamespace(is_available=lambda: True)}
        converter.convert_batch.return_value = copy.deepcopy(
            self.records if records is None else records
        )
        if infrastructure:
            converter.convert_batch.side_effect = ResourceAdmissionError(
                "controlled admission failure"
            )
        with (
            patch.object(sys, "argv", argv),
            patch.object(run_smiles, "SmilesConverter", return_value=converter),
        ):
            run_smiles.main()
        return output, converter

    def _review_records(self):
        records = copy.deepcopy(self.records)
        records[0].update(
            status="review_required",
            OCSR_quality_flag="review_required",
            error="controlled source chemistry review",
        )
        return records

    def test_real_worker_entry_completes_findings_without_retagging_review(self):
        records = self._review_records()
        output, _ = self._cli(records=records)
        actual = smiles_records(json.loads(output.read_text()))
        self.assertEqual(actual, records)
        marker = json.loads(failure_marker_path(output.parent).read_text())
        self.assertFalse(marker["deliverables_accepted"])
        self.assertTrue(marker["errors"])

    def test_real_worker_default_still_rejects_the_same_findings(self):
        with self.assertRaisesRegex(RuntimeError, "Strict OCSR output gate failed"):
            self._cli(continuation=False, records=self._review_records())

    def test_real_worker_limit_is_rejected_before_conversion(self):
        with self.assertRaisesRegex(ValueError, "cannot be diagnostic"):
            self._cli(extra=("--limit", "1"))
        self.assertFalse((self.root / "worker-output/smiles.json").exists())

    def test_real_worker_diagnostic_mode_cannot_use_source_completion(self):
        with self.assertRaisesRegex(ValueError, "cannot be diagnostic"):
            self._cli(extra=("--diagnostic-unvalidated-input",))
        self.assertFalse((self.root / "worker-output/smiles.json").exists())

    def test_real_worker_infrastructure_exception_is_never_a_scientific_completion(
        self,
    ):
        with self.assertRaisesRegex(
            ResourceAdmissionError, "controlled admission failure"
        ):
            self._cli(infrastructure=True)
        self.assertFalse((self.root / "worker-output/smiles.json").exists())

    def test_real_worker_missing_observation_is_rejected_before_publication(self):
        with self.assertRaisesRegex(
            ValueError, "incomplete, duplicated or misassigned"
        ):
            self._cli(records=self.records[:1])
        self.assertFalse((self.root / "worker-output/smiles.json").exists())
