"""Known GPU probe failures are explicit; programming bugs never disappear."""

import unittest
from unittest.mock import patch

from patent_sar_extractor.application import worker_policy


class WorkerProbeTests(unittest.TestCase):
    def test_expected_probe_failure_is_redacted_and_selects_cpu(self):
        with (
            patch.object(worker_policy, "_DECIMER_TF_GPU_SAFE", None),
            patch.object(
                worker_policy, "_host_gpu_compute_capability", return_value="12.0"
            ),
            patch.object(
                worker_policy, "run_snippet", side_effect=OSError("private-value")
            ),
            self.assertLogs("patent_sar_extractor", level="WARNING") as logs,
        ):
            self.assertFalse(worker_policy._decimer_tensorflow_gpu_safe())
            self.assertNotIn("private-value", str(logs.output))
            self.assertIn("OSError", str(logs.output))

    def test_unexpected_programming_failure_does_not_silently_select_cpu(self):
        with (
            patch.object(worker_policy, "_DECIMER_TF_GPU_SAFE", None),
            patch.object(
                worker_policy, "_host_gpu_compute_capability", return_value="12.0"
            ),
            patch.object(
                worker_policy, "run_snippet", side_effect=AssertionError("unexpected")
            ),
            self.assertRaises(AssertionError),
        ):
            worker_policy._decimer_tensorflow_gpu_safe()
