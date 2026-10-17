"""Bounded private excerpts preserve error endings, not worker acceptance."""

import subprocess
import unittest

from patent_sar_extractor.application.worker_diagnostics import worker_error_details


class WorkerDiagnosticTests(unittest.TestCase):
    def test_large_diagnostic_is_explicitly_bounded_with_its_terminal_cause(self):
        cause = "ValueError: controlled terminal cause"
        raw = "Traceback: original caller\n" + "x" * 100000 + "\n" + cause
        result = subprocess.CompletedProcess(["controlled"], 3, "", raw)
        with self.assertLogs("patent_sar_extractor", level="ERROR") as logs:
            excerpt = worker_error_details(result, "controlled")
        self.assertLessEqual(len(excerpt), 1200)
        self.assertIn(cause, excerpt)
        self.assertIn("truncated", excerpt)
        self.assertIn("Traceback", excerpt)
        self.assertIn(cause, logs.output[0])
        self.assertLess(len(logs.output[0]), 66000)

    def test_empty_failure_includes_its_nonzero_return_code(self):
        with self.assertLogs("patent_sar_extractor", level="ERROR"):
            excerpt = worker_error_details(
                subprocess.CompletedProcess(["controlled"], 7, "", ""), "controlled"
            )
        self.assertIn("7", excerpt)
        self.assertIn("without diagnostic output", excerpt)

    def test_stderr_is_preferred_without_losing_short_text(self):
        with self.assertLogs("patent_sar_extractor", level="ERROR"):
            excerpt = worker_error_details(
                subprocess.CompletedProcess(["controlled"], 1, "stdout", "stderr"),
                "controlled",
            )
        self.assertEqual(excerpt, "stderr")


if __name__ == "__main__":
    unittest.main()
