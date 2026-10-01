from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from patent_sar_extractor.application.commands import (
    cmd_run,
)
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.application.worker_policy import (
    _run_activity_rules,
)


class ExtractionProgressTests(unittest.TestCase):
    def test_real_stage_is_persisted_before_work_and_failure_preserves_gate_errors(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            log = {
                "main_chain": ["classify", "activity"],
                "steps": {},
                "status": "running",
            }
            progress = PipelineProgress()
            progress.bind(temporary, log)
            progress.start("classify")
            saved = json.loads((Path(temporary) / "pipeline_summary.json").read_text())
            self.assertEqual(saved["steps"], {"classify": {"status": "running"}})
            log["status"] = "failed_accuracy_gate"
            log["steps"]["classify"]["acceptance_errors"] = ["Source evidence conflict"]
            progress.fail_current()
            saved = json.loads((Path(temporary) / "pipeline_summary.json").read_text())
            self.assertEqual(saved["steps"]["classify"]["status"], "failed")
            self.assertEqual(
                saved["steps"]["classify"]["acceptance_errors"],
                ["Source evidence conflict"],
            )
            self.assertEqual(saved["status"], "failed_accuracy_gate")

    def test_classification_exception_is_not_left_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            pdf = Path(temporary) / "input.pdf"
            pdf.write_bytes(b"controlled unavailable PDF")
            args = SimpleNamespace(
                pdf=str(pdf), output=temporary, patent_id="TEST-PATENT"
            )
            with patch(
                "patent_sar_extractor.application.stage_classify.classify_pdf",
                side_effect=RuntimeError("OCR failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "OCR failure"):
                    cmd_run(args)
            saved = json.loads((Path(temporary) / "pipeline_summary.json").read_text())
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["steps"]["classify"]["status"], "failed")
            self.assertNotIn("activity", saved["steps"])

    def test_patent_identity_is_passed_to_activity_worker(self):
        with patch(
            "patent_sar_extractor.application.worker_policy.run_snippet",
            return_value=SimpleNamespace(returncode=0),
        ) as run:
            _run_activity_rules("original.pdf", {}, "output", patent_id="TEST-PATENT")
        self.assertIn("'patent_id': 'TEST-PATENT'", run.call_args.args[1])
