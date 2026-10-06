"""Workload lifetime and source-led stage failure propagation, without ML."""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from patent_sar_extractor import contracts
from patent_sar_extractor.application.pipeline_context import PipelineContext
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.application.recognition_budget import (
    MAX_PIPELINE_SECONDS,
    recognition_timeout,
)
from patent_sar_extractor.application.scientific_status import CoreNotAcceptedError
from patent_sar_extractor.application.stage_qa import execute_qa
from patent_sar_extractor.application.stage_smiles import execute_smiles
from tests.test_source_led_export import run_fixture
from tests.test_source_led_pipeline import state_for


class SourceLedStageTests(unittest.TestCase):
    def test_workload_budget_is_finite_and_capped_by_parent_remaining_lifetime(self):
        with patch(
            "patent_sar_extractor.application.recognition_budget.time.monotonic",
            return_value=1000,
        ):
            self.assertEqual(recognition_timeout(1, 1000), 1800)
            self.assertEqual(recognition_timeout(100, 1000), 30600)
            self.assertEqual(recognition_timeout(1000000, 1000), MAX_PIPELINE_SECONDS)
            self.assertEqual(
                recognition_timeout(100, 1000 - MAX_PIPELINE_SECONDS + 60), 60
            )
            with self.assertRaises(TimeoutError):
                recognition_timeout(1, 1000 - MAX_PIPELINE_SECONDS)
        with self.assertRaises(ValueError):
            recognition_timeout(-1, 0)

    def test_smiles_runs_all_catalog_records_with_no_activity_and_workload_deadline(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_fixture(root)
            state = state_for(root, "smiles")
            state.step_dirs["smiles"] = str(root / "smiles")
            state.bind_json = str(root / "structure_bindings/bindings.json")
            state.bind_payload = json.loads(Path(state.bind_json).read_text())
            state.n_bound = 2
            state.active_cpds = []
            state.force = True
            payload = json.loads((root / "smiles/smiles_results.json").read_text())
            payload["generated_by"] = "synthetic freshly published producer control"

            def producer(*args, **kwargs):
                Path(state.smiles_json).write_text(json.dumps(payload))
                return CompletedProcess([], 0, "", "")

            with (
                patch(
                    "patent_sar_extractor.application.stage_smiles.DECIMEREngine.runtime_identity",
                    return_value={"fingerprint": "a" * 64},
                ),
                patch(
                    "patent_sar_extractor.application.stage_smiles.run_in_env",
                    side_effect=producer,
                ) as worker,
                patch(
                    "patent_sar_extractor.application.stage_smiles.recognition_timeout",
                    return_value=1800,
                ) as budget,
            ):
                execute_smiles(state)
            self.assertEqual(worker.call_args.kwargs["timeout"], 1800)
            budget.assert_called_once_with(2, state.started_monotonic)
            self.assertEqual(state.pipeline_log["steps"]["smiles"]["formal_total"], 2)
            self.assertEqual(state.pipeline_log["steps"]["smiles"]["source_total"], 0)

    def test_infrastructure_failure_stops_with_no_relaunch_or_retagging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_fixture(root)
            state = state_for(root, "smiles")
            state.step_dirs["smiles"] = str(root / "smiles")
            state.bind_json = str(root / "structure_bindings/bindings.json")
            state.bind_payload = json.loads(Path(state.bind_json).read_text())
            state.n_bound = 2
            state.force = True
            prior = (root / "smiles/smiles_results.json").read_bytes()
            with (
                patch(
                    "patent_sar_extractor.application.stage_smiles.DECIMEREngine.runtime_identity",
                    return_value={"fingerprint": "a" * 64},
                ),
                patch(
                    "patent_sar_extractor.application.stage_smiles.run_in_env",
                    return_value=CompletedProcess(
                        [], 1, "", "model infrastructure unavailable"
                    ),
                ) as worker,
                self.assertRaisesRegex(RuntimeError, "smiles failed"),
            ):
                execute_smiles(state)
            worker.assert_called_once()
            self.assertEqual((root / "smiles/smiles_results.json").read_bytes(), prior)
            self.assertFalse(Path(state.smiles_json + ".manifest.json").exists())
            self.assertNotIn("qa", state.pipeline_log["steps"])

    def test_terminal_rejection_keeps_exact_eight_stage_summary_and_core_not_accepted(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_fixture(root)
            progress = PipelineProgress()
            log = {
                **contracts.artifact_identity(
                    contracts.RUN_SUMMARY_SCHEMA, contracts.RUN_SUMMARY_SCHEMA_VERSION
                ),
                "main_chain": list(contracts.CORE_STAGE_ORDER),
                "status": "running",
                "steps": {
                    stage: {"status": "ok", "elapsed_s": 0.1}
                    for stage in contracts.CORE_STAGE_ORDER[:-1]
                },
                "scientific_errors": {"activity": ["known activity rows were lost"]},
            }
            progress.bind(str(root), log)
            state = PipelineContext(
                args=Namespace(skip_advisory_qa=True),
                progress=progress,
                base_dir=str(root),
                patent_id="CONTROL",
                pipeline_log=log,
                strict_gates=True,
                scientific_errors=log["scientific_errors"],
            )
            with (
                patch(
                    "patent_sar_extractor.application.stage_qa.run_advisory_qa",
                    return_value={"status": "skipped", "warnings": []},
                ),
                self.assertRaises(CoreNotAcceptedError) as failure,
            ):
                execute_qa(state)
            self.assertEqual(failure.exception.code, "core_not_accepted")
            summary = json.loads((root / "pipeline_summary.json").read_text())
            self.assertEqual(summary["main_chain"], list(contracts.CORE_STAGE_ORDER))
            self.assertEqual(set(summary["steps"]), set(contracts.CORE_STAGE_ORDER))
            self.assertEqual(summary["steps"]["qa"]["status"], "failed")
            self.assertFalse(summary["steps"]["qa"]["strict_acceptance_ok"])
            self.assertTrue(summary["steps"]["qa"]["hard_errors"])
            self.assertEqual(summary["status"], "failed_accuracy_gate")
            self.assertEqual(summary["error"]["code"], "core_not_accepted")
            # The existing cmd_run exception adapter must retain the QA rejection.
            state.progress.fail_current()
            terminal = json.loads((root / "pipeline_summary.json").read_text())
            self.assertEqual(terminal["status"], "failed_accuracy_gate")
            self.assertFalse(terminal["steps"]["qa"]["strict_acceptance_ok"])


if __name__ == "__main__":
    unittest.main()
