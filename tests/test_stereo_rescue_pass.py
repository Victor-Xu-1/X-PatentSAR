"""Focused queue/proof/lifecycle controls; SDK accuracy uses separate native evidence."""

from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from patent_sar_extractor.core.ocsr.conversion_progress import ConversionProgress
from patent_sar_extractor.core.ocsr.smiles_converter import SmilesConverter
from patent_sar_extractor.core.ocsr.smiles_qc import qc_smiles
from patent_sar_extractor.core.ocsr.stereo_evidence import (
    observe_stereo_symbols,
    source_checked_qc,
)
from patent_sar_extractor.core.ocsr.stereo_gate import validate_stereo_record
from patent_sar_extractor.core.ocsr.stereo_rescue_pass import (
    apply_stereo_rescue,
    validate_rescue_proof,
)

PARTIAL, PAIRED = "C[C@H]1CC(C)(O)C1", "C[C@H]1C[C@](C)(O)C1"


class Engine:
    session_exhausted = False

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class RescuePassTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / "source.png"
        Image.new("RGB", (80, 80), "white").save(self.source)
        checked = source_checked_qc(
            qc_smiles(PARTIAL), observe_stereo_symbols(self.source)
        )
        self.record = {
            **checked,
            "raw_smiles": PARTIAL,
            "canonical_smiles": checked["canonical_smiles"],
            "OCSR_engine": "decimer",
            "OCSR_status": "review_required",
            "OCSR_quality_flag": "stereochemistry_not_retained",
            "model_fingerprint": "a" * 64,
            "image_hash": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "engine_attempts": [{"engine": "decimer", "raw_smiles": PARTIAL}],
        }
        self.engine = Engine()
        self.calls = []

    def predict(self, name, engine, source):
        self.calls.append((name, source))
        return {
            "status": "success",
            "raw_smiles": PAIRED,
            "model_fingerprint": "b" * 64,
            "device": "cpu",
            "peak_rss_mb": 1800,
            "model_confidence": 0.7,
        }, {}

    def run_pass(self, records=None, sources=None, predict=None):
        records = records or [copy.deepcopy(self.record)]
        progress = ConversionProgress("", len(records))
        for record in records:
            progress.record(record)
        with patch(
            "patent_sar_extractor.core.ocsr.stereo_rescue_pass.MolScribeEngine",
            return_value=self.engine,
        ) as factory:
            result = apply_stereo_rescue(
                records,
                sources or [str(self.source)] * len(records),
                predict or self.predict,
                engine_configs={},
                progress=progress,
            )
        return result, progress, factory

    def test_replacement_preserves_raw_provenance_and_revalidates_proof(self):
        result, progress, _ = self.run_pass()
        row = result[0]
        self.assertEqual(row["raw_smiles"], PAIRED)
        self.assertEqual(row["OCSR_engine"], "molscribe")
        self.assertEqual(row["stereo_rescue_proof"]["primary_raw_smiles"], PARTIAL)
        self.assertEqual(row["engine_attempts"][0]["raw_smiles"], PARTIAL)
        self.assertEqual(self.record["raw_smiles"], PARTIAL)
        self.assertEqual(progress.payload["completed"], 1)
        self.assertEqual(progress.payload["failures"], 0)
        self.assertTrue(self.engine.closed)
        self.assertEqual(validate_stereo_record(row)["status"], "no_unknown_detected")

    def test_each_tampered_proof_or_source_is_rejected_by_shared_consumer(self):
        rows, _, _ = self.run_pass()
        for key, value in (
            ("primary_raw_smiles", "CCO"),
            ("source_image_sha256", "c" * 64),
            ("candidate_model_fingerprint", "c" * 64),
            ("decision", {"accepted": True}),
        ):
            row = copy.deepcopy(rows[0])
            row["stereo_rescue_proof"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_stereo_record(row)
        row = copy.deepcopy(rows[0])
        del row["stereo_rescue_proof"]
        with self.assertRaises(ValueError):
            validate_rescue_proof(row)

    def test_normal_or_source_ambiguous_rows_never_start_second_engine(self):
        for changes in (
            {"OCSR_quality_flag": "ok"},
            {"OCSR_engine": "other"},
            {
                "stereochemistry": {
                    "status": "ambiguous",
                    "unknown_bond_boxes": [[1, 1, 5, 5]],
                }
            },
        ):
            row = {**copy.deepcopy(self.record), **changes}
            rows, _, factory = self.run_pass([row])
            factory.assert_not_called()
            self.assertEqual(rows[0]["raw_smiles"], PARTIAL)

    def test_wrong_graph_remains_review(self):
        def wrong(*args):
            result, notes = self.predict(*args)
            result["raw_smiles"] = "N[C@H]1C[C@](C)(O)C1"
            return result, notes

        rows, progress, _ = self.run_pass(predict=wrong)
        self.assertEqual(rows[0]["OCSR_status"], "review_required")
        self.assertEqual(rows[0]["raw_smiles"], PARTIAL)
        self.assertEqual(progress.payload["failures"], 1)

    def test_budget_is_eight_and_does_not_inflate_progress(self):
        rows, progress, _ = self.run_pass(
            [copy.deepcopy(self.record) for _ in range(10)]
        )
        self.assertEqual(len(self.calls), 8)
        self.assertEqual(sum(row["OCSR_status"] == "success" for row in rows), 8)
        self.assertEqual(progress.payload["completed"], 10)
        self.assertEqual(progress.payload["total"], 10)
        self.assertEqual(progress.payload["failures"], 2)

    def test_source_identity_change_refuses_before_prediction(self):
        row = {**copy.deepcopy(self.record), "image_hash": "c" * 64}
        rows, _, _ = self.run_pass([row])
        self.assertFalse(self.calls)
        self.assertEqual(
            rows[0]["local_stereo_rescue"]["reason"], "source_identity_changed"
        )

    def test_exception_still_reaps_owned_engine(self):
        def cancelled(*args):
            raise InterruptedError("controlled cancellation")

        with self.assertRaises(InterruptedError):
            self.run_pass(predict=cancelled)
        self.assertTrue(self.engine.closed)

    def test_bounded_second_proof_refusal_keeps_primary_review_and_batch(self):
        from patent_sar_extractor.core.ocsr.stereo_rescue import validate_stereo_rescue

        approved = validate_stereo_rescue(
            PARTIAL, PAIRED, primary_quality_flag="stereochemistry_not_retained"
        )
        refusal = {**approved, "accepted": False, "reason": "time_budget_exceeded"}
        with patch(
            "patent_sar_extractor.core.ocsr.stereo_rescue_pass.validate_stereo_rescue",
            side_effect=[approved, refusal],
        ):
            rows, progress, _ = self.run_pass()
        self.assertEqual(rows[0]["raw_smiles"], PARTIAL)
        self.assertEqual(rows[0]["OCSR_status"], "review_required")
        self.assertEqual(
            rows[0]["local_stereo_rescue"]["reason"], "time_budget_exceeded"
        )
        self.assertEqual(progress.payload["failures"], 1)
        self.assertTrue(self.engine.closed)

    def test_converter_reaps_primary_before_constructing_rescue_engine(self):
        primary = Engine()
        primary.is_available = lambda: True
        primary.predict = lambda *args, **kwargs: {
            "status": "success",
            "raw_smiles": PARTIAL,
            "model_fingerprint": "a" * 64,
        }
        rescue = Engine()
        rescue.is_available = lambda: True
        rescue.predict = lambda *args, **kwargs: {
            "status": "success",
            "raw_smiles": PAIRED,
            "model_fingerprint": "b" * 64,
        }

        def make_rescue(**kwargs):
            self.assertTrue(primary.closed)
            return rescue

        with (
            patch.dict(
                "patent_sar_extractor.core.ocsr.smiles_converter.ENGINE_MAP",
                {"decimer": lambda **kwargs: primary},
            ),
            patch(
                "patent_sar_extractor.core.ocsr.stereo_rescue_pass.MolScribeEngine",
                side_effect=make_rescue,
            ),
        ):
            converter = SmilesConverter(["decimer"], [], preprocess=False)
            results = converter.convert_batch(
                [
                    {
                        "cpd": "Compound 1",
                        "image_path": str(self.source),
                        "bind_status": "bound",
                    }
                ]
            )
        self.assertEqual(results[0]["OCSR_engine"], "molscribe")
        self.assertTrue(rescue.closed)
        validate_stereo_record(results[0])
