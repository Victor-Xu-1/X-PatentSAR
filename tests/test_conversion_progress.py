from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from patent_sar_extractor.core.ocsr.conversion_progress import ConversionProgress


class ConversionProgressTests(unittest.TestCase):
    def test_persists_actual_counts_and_does_not_reuse_old_process_memory(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "progress.json"
            progress = ConversionProgress(str(path), 3)
            progress.record(
                {
                    "OCSR_status": "success",
                    "device": "cpu",
                    "peak_rss_mb": 700,
                    "engine_attempts": [],
                }
            )
            progress.record(
                {
                    "OCSR_status": "success",
                    "device": "gpu",
                    "peak_rss_mb": 5000,
                    "engine_attempts": [{"from_cache": True}],
                }
            )
            progress.record({"OCSR_status": "failed", "engine_attempts": []})
            saved = json.loads(path.read_text())
            self.assertEqual(saved["completed"], 3)
            self.assertEqual(saved["total"], 3)
            self.assertEqual(saved["cache_hits"], 1)
            self.assertEqual(saved["failures"], 1)
            self.assertEqual(saved["device"], "cpu")
            self.assertEqual(saved["peak_rss_mb"], 700)

    def test_nan_memory_is_not_persisted_as_a_metric(self):
        progress = ConversionProgress("", 1)
        progress.record({"OCSR_status": "success", "peak_rss_mb": float("nan")})
        self.assertIsNone(progress.payload["peak_rss_mb"])
