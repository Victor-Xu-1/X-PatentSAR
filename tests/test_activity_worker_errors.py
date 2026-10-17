"""Preserve terminal worker causes without running or repairing user data."""

import subprocess
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from patent_sar_extractor.application import worker_policy


class ActivityWorkerErrorTests(unittest.TestCase):
    def invoke(self, result):
        capture = (
            self.assertLogs("patent_sar_extractor", level="ERROR")
            if result.returncode
            else nullcontext()
        )
        with patch.object(worker_policy, "run_snippet", return_value=result), capture:
            worker_policy._run_activity_rules(
                pdf_path="controlled-input.pdf",
                classification={"activity_pages": [], "synthesis_pages": []},
                output_dir="controlled-output",
            )

    def test_long_call_context_does_not_hide_the_terminal_exception(self):
        terminal = "ValueError: controlled original-header inconsistency"
        stderr = (
            "Traceback (most recent call last):\n" + "argument " * 900 + "\n" + terminal
        )
        with self.assertRaisesRegex(RuntimeError, terminal):
            self.invoke(subprocess.CompletedProcess(["controlled"], 1, "", stderr))

    def test_whitespace_stderr_does_not_hide_actual_stdout_failure(self):
        with self.assertRaisesRegex(RuntimeError, "controlled worker cause"):
            self.invoke(
                subprocess.CompletedProcess(
                    ["controlled"], 2, "controlled worker cause", " \n"
                )
            )

    def test_success_is_not_reclassified_by_unrelated_stderr(self):
        self.invoke(
            subprocess.CompletedProcess(["controlled"], 0, "", "controlled SDK note")
        )


if __name__ == "__main__":
    unittest.main()
