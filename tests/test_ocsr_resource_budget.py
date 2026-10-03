"""Model headroom and owned-worker limits do not affect other applications."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.ocsr.resource_budget import (
    check_model_headroom,
    resident_budget_mb,
    worker_resident_mb,
)
from patent_sar_extractor.core.ocsr.worker_process import (
    JsonLineWorker,
    WorkerProtocolError,
)


class OCSRResourceBudgetTests(unittest.TestCase):
    def test_default_budget_and_invalid_bounds(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resident_budget_mb(), 4096)
        for value in ("0", "2047", "16385", "bad"):
            with (
                self.subTest(value=value),
                patch.dict(os.environ, {"PATENTSAR_DECIMER_MAX_RSS_MB": value}),
            ):
                with self.assertRaises(ValueError):
                    resident_budget_mb()

    def test_low_headroom_fails_before_model_import(self):
        with patch("pathlib.Path.read_text", return_value="MemAvailable: 1024 kB\n"):
            with self.assertRaisesRegex(RuntimeError, "No model was loaded"):
                check_model_headroom()
        with patch("pathlib.Path.read_text", return_value="MemAvailable: 4194304 kB\n"):
            check_model_headroom()

    def test_owned_process_rss_and_exit_are_observable(self):
        self.assertGreater(worker_resident_mb(os.getpid()), 0)
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            self.assertIsNone(worker_resident_mb(99999999))

    def test_receive_fails_when_owned_worker_exceeds_budget(self):
        from types import SimpleNamespace

        worker = JsonLineWorker.__new__(JsonLineWorker)
        worker.process = SimpleNamespace(pid=123)
        with patch(
            "patent_sar_extractor.core.ocsr.worker_process.worker_resident_mb",
            return_value=4097,
        ):
            with self.assertRaisesRegex(WorkerProtocolError, "memory budget"):
                worker.receive(1)
