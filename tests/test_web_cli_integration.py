"""A real, tiny core CLI failure case; never invokes paid QA or DECIMER."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from test_web_support import WebFixture, make_pdf


class CoreCLIIntegrationTests(WebFixture, unittest.TestCase):
    def test_real_minimal_pdf_fails_strict_activity_gate(self):
        pdf = make_pdf(
            self.root / "minimal.pdf",
            text="This controlled native text document contains no activity table or chemical results.",
        )
        output = self.root / "cli-output"
        config = self.root / "operator-config"
        config.mkdir(mode=0o700)
        env = {
            **os.environ,
            "PATENTSAR_CONFIG_DIR": str(config),
            "PATENTSAR_BASE_PYTHON": sys.executable,
            "LLM_API_KEY": "",
            "CUDA_VISIBLE_DEVICES": "-1",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
        }
        command = [
            sys.executable,
            "-m",
            "patent_sar_extractor",
            "run",
            "--pdf",
            str(pdf),
            "--output",
            str(output),
            "--patent-id",
            "LOCAL-STRICT-GATE",
            "--gpu-mode",
            "off",
            "--locate-workers",
            "1",
            "--bind-workers",
            "1",
            "--smiles-workers",
            "1",
        ]
        # The strict activity failure occurs before advisory QA. This intentionally
        # also runs against the baseline CLI, before the controller adds its new
        # --skip-advisory-qa flag; it does not alter the production Web runner.
        result = subprocess.run(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        marker = json.loads((output / "STRICT_ACCEPTANCE_FAILED.json").read_text())
        summary = json.loads((output / "pipeline_summary.json").read_text())
        self.assertEqual(marker["stage"], "activity")
        self.assertEqual(summary["steps"]["activity"]["status"], "failed")
        self.assertNotIn("smiles", summary["steps"])
        self.assertFalse((output / "llm_qa_report.json").exists())
        self.assertFalse((output / "final_qa_report.json").exists())
