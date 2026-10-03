from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class StructureWorkerContractTests(unittest.TestCase):
    def test_missing_decimer_is_a_real_failure_not_an_empty_fallback(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "src/patent_sar_extractor/workers/extract_structures.py"
        )
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "output"
            environment = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1"}
            result = subprocess.run(
                [
                    sys.executable,
                    str(worker),
                    "--pdf",
                    "missing.pdf",
                    "--output",
                    str(out),
                    "--patent-id",
                    "CONTROLLED",
                    "--pages",
                    "0",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                env=environment,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("DECIMER segmentation is unavailable", result.stderr)
            self.assertNotIn("using basic image-based extraction", result.stderr)
            self.assertFalse((out / "metadata.json").exists())
