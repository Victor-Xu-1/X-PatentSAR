"""Saved raw completion is checked by the same QC/Web consumers, without inference."""

import copy
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from recognition_source_support import observation

import patent_sar_extractor
from patent_sar_extractor.core.ocsr.generation import observe_generation
from patent_sar_extractor.core.ocsr.recognition_policy import record_errors
from patent_sar_extractor.core.ocsr.stereo_gate import validate_stereo_record
from patent_sar_extractor.web.recognition import recognition_status
from patent_sar_extractor.web.source_epoch import record_epoch_current


class GenerationConsumerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        image = Path(temporary.name) / "generated.png"
        Image.new("RGB", (80, 80), "white").save(image)
        self.row = observation(
            {
                "image_path": str(image),
                "cpd": "Example A-2",
                "structure_id": "S1",
                "page_no": 1,
            }
        )

    def test_complete_current_observation_remains_usable(self):
        self.assertFalse(record_errors(self.row))
        self.assertTrue(record_epoch_current(self.row))
        self.assertEqual(recognition_status(self.row, current=True)["status"], "valid")

    def test_legacy_raw_stays_historical_not_current_or_accepted(self):
        row = copy.deepcopy(self.row)
        row.pop("generation")
        before = copy.deepcopy(row)
        self.assertFalse(record_epoch_current(row))
        self.assertTrue(record_errors(row))
        self.assertEqual(
            recognition_status(row, current=False)["status"], "unavailable"
        )
        self.assertEqual(row, before)

    def test_complete_tokens_for_another_raw_molecule_cannot_pass(self):
        row = copy.deepcopy(self.row)
        row["generation"] = observe_generation(["<start>", "C", "N", "<end>"])[1]
        self.assertFalse(record_epoch_current(row))
        with self.assertRaises(ValueError):
            validate_stereo_record(row)

    def test_parseable_incomplete_raw_cannot_be_self_promoted(self):
        row = copy.deepcopy(self.row)
        row["generation"] = observe_generation(["<start>", "C", "C", "O"])[1]
        self.assertTrue(record_errors(row))
        with self.assertRaises(ValueError):
            validate_stereo_record(row)

    def test_current_failed_raw_is_visible_without_becoming_valid(self):
        row = copy.deepcopy(self.row)
        row["generation"] = observe_generation(["<start>", "C", "C", "O"])[1]
        row["OCSR_status"] = "all_engines_failed"
        before = copy.deepcopy(row)
        self.assertTrue(record_epoch_current(row))
        self.assertEqual(recognition_status(row, current=True)["status"], "unavailable")
        self.assertTrue(record_errors(row))
        self.assertEqual(row, before)

    def test_forged_completion_flag_is_not_a_current_observation(self):
        row = copy.deepcopy(self.row)
        row["generation"]["tokens"].pop()
        self.assertFalse(record_epoch_current(row))
        self.assertTrue(record_errors(row))

    def test_deleting_or_relabelling_engine_identity_cannot_bypass_completion(self):
        for engine in (None, "other", "molscribe"):
            row = {**self.row, "OCSR_engine": engine}
            row.pop("generation")
            with self.subTest(engine=engine):
                self.assertFalse(record_epoch_current(row))
                self.assertTrue(record_errors(row))

    def test_actual_research_worker_boundary_requires_matching_complete_tokens(self):
        worker = (
            Path(patent_sar_extractor.__file__).parent
            / "workers/analysis_decimer_worker.py"
        )
        recognize = runpy.run_path(str(worker))["recognize"]
        valid = {"smiles": "CCO", "generation": self.row["generation"]}
        identity = {"versions": {"DECIMER": "controlled"}}

        def call(prediction):
            with patch.dict(
                recognize.__globals__,
                {
                    "printed_model_identity": lambda: identity,
                    "PrintedDecimerModel": lambda _identity: SimpleNamespace(
                        predict=lambda _path: prediction
                    ),
                },
            ):
                return recognize({"image_path": self.row["ocsr_original_input"]})

        self.assertEqual(call(valid)["raw_smiles"], "CCO")
        for changed in (
            {**valid, "generation": None},
            {**valid, "generation": observe_generation(["<start>", "C", "C", "O"])[1]},
            {**valid, "smiles": "CCN"},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                call(changed)
