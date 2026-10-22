"""Generated originals: conserve every crop without recognizing unproved owners."""

import contextlib
import copy
import io
import sys
import unittest
from unittest.mock import patch

from test_candidate_stage import CandidateStageControls

from patent_sar_extractor.application import stage_smiles
from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.ocsr import run_smiles
from patent_sar_extractor.core.ocsr.candidate_coverage import candidate_coverage_errors
from patent_sar_extractor.core.ocsr.recognition_inputs import RecognitionPlan
from patent_sar_extractor.smiles_artifact import smiles_observations


class TerminalRecognitionScopeTests(CandidateStageControls, unittest.TestCase):
    def test_retired_unbound_worker_flags_cannot_restore_an_inference_path(self):
        for option in ("--include-unbound", "--include-intermediates", "--only-bound"):
            with (
                self.subTest(option=option),
                patch.object(sys, "argv", ["worker", "--input", "unused.json", option]),
                contextlib.redirect_stderr(io.StringIO()),
                patch.object(
                    run_smiles,
                    "SmilesConverter",
                    side_effect=AssertionError("Invalid flags cannot load a model"),
                ),
                self.assertRaises(SystemExit) as failure,
            ):
                run_smiles.main()
            self.assertEqual(failure.exception.code, 2)

    def test_unproved_crops_never_enter_the_model_work_queue(self):
        plan = self.plan()
        before = copy.deepcopy(self.metadata)
        self.assertEqual([row["cpd"] for row in plan.work_items], ["Compound 7"])
        self.assertEqual(len(plan.candidates), 1)
        self.assertEqual(len(plan.inventory["entries"]), 2)
        self.assertEqual(self.metadata, before)

    def test_an_empty_proved_catalogue_captures_inventory_without_loading_models(self):
        state = self.state()
        forbidden = AssertionError("No proved terminal owner: no model or worker")
        with (
            patch.object(stage_smiles, "run_in_env", side_effect=forbidden),
            patch.object(stage_smiles, "DECIMEREngine", side_effect=forbidden),
            patch.object(stage_smiles, "MolScribeEngine", side_effect=forbidden),
            patch.object(stage_smiles, "_gpu_env_extra", side_effect=forbidden),
        ):
            stage_smiles.execute_smiles(state)
        artifact = load_json(state.smiles_json, {})
        self.assertEqual(smiles_observations(artifact), [])
        self.assertEqual(len(artifact["candidate_inventory"]["entries"]), 2)
        self.assertEqual(len(artifact["candidate_records"]), 2)
        for row in artifact["candidate_records"]:
            self.assertEqual(row["OCSR_status"], "not_processed")
            self.assertIsNone(row["raw_smiles"])
            self.assertIsNone(row["model_fingerprint"])
        step = state.pipeline_log["steps"]["smiles"]
        self.assertEqual(step["total"], 0)
        self.assertEqual(step["deferred_total"], 2)
        self.assertEqual(step["execution_status"], "not_started")
        self.assertEqual(step["blocked_by"], "bind")
        self.assertTrue(state.scientific_errors["smiles"])
        self.assertEqual(
            candidate_coverage_errors(
                self.output,
                {"input_pdf": str(self.pdf)},
                self.metadata,
                self.bindings,
                artifact,
            ),
            [],
        )

    def test_direct_converter_cannot_reenable_unproved_candidate_inference(self):
        candidate = self.plan().candidates[0]
        for mode in ("one", "prepared", "batch", "include_unbound"):
            converter = self.converter()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                if mode == "one":
                    converter.convert_one(candidate)
                elif mode == "prepared":
                    converter.convert_one(
                        candidate, prepared={"ready": True, "result": {}}
                    )
                else:
                    converter.convert_batch(
                        [candidate], only_bound=mode != "include_unbound"
                    )
            self.assertEqual(converter.engines["decimer"].calls, [])
            converter.close()

    def test_standalone_worker_does_not_probe_or_construct_models_for_empty_selection(
        self,
    ):
        output = self.output / "standalone" / "smiles.json"
        arguments = [
            "worker",
            "--input",
            str(self.bind_path),
            "--structures",
            str(self.metadata_path),
            "--source-pdf",
            str(self.pdf),
            "--output",
            str(output),
            "--csv-output",
            str(output.with_suffix(".csv")),
            "--cache",
            str(output.with_suffix(".sqlite")),
            "--continue-on-scientific-errors",
        ]
        with (
            patch.object(sys, "argv", arguments),
            patch.object(
                run_smiles,
                "SmilesConverter",
                side_effect=AssertionError("Empty selection cannot load a model"),
            ),
        ):
            run_smiles.main()
        artifact = load_json(output, {})
        self.assertEqual(smiles_observations(artifact), [])
        self.assertEqual(len(artifact["candidate_records"]), 2)
        self.assertFalse(output.with_suffix(".sqlite").exists())

    def test_explicit_intermediate_cannot_borrow_numbered_model_eligibility(self):
        for label in ("Intermediate 7", "中间体 7", "Intermediates 7"):
            owner = {**self.owner, "cpd": label}
            with self.subTest(label=label), self.assertRaises(ValueError):
                self.plan(sources=RecognitionPlan([owner], [], []))


if __name__ == "__main__":
    unittest.main()
