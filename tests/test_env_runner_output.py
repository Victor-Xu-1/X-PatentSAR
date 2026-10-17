"""Real configured Python children: bounded diagnostics and deadline-safe I/O."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.core import env_runner


@unittest.skipUnless(os.name == "posix", "Native Linux/WSL subprocess pipes")
class EnvironmentOutputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="patentsar-worker-output-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"PATENTSAR_BASE_PYTHON": sys.executable})
        environment.start()
        self.addCleanup(environment.stop)

    def run_child(self, code, *, stream=False, timeout=5):
        script = self.root / "controlled_worker.py"
        script.write_text(code, encoding="utf-8")
        return env_runner.run_in_env(
            "base", str(script), timeout=timeout, stream_output=stream
        )

    def test_capture_bounds_both_pipes_and_preserves_terminal_failure(self):
        result = self.run_child(
            "import os, sys\n"
            "os.write(1, b'OUT-START\\n' + b'x' * 2_000_000 + b'\\nOUT-END\\n')\n"
            "os.write(2, b'ERR-START\\n' + b'y' * 2_000_000 + b'\\nValueError: terminal cause\\n')\n"
            "sys.exit(9)\n"
        )
        self.assertEqual(result.returncode, 9)
        for output, first, last in (
            (result.stdout, "OUT-START", "OUT-END"),
            (result.stderr, "ERR-START", "ValueError: terminal cause"),
        ):
            with self.subTest(pipe=first):
                self.assertLessEqual(len(output.encode("utf-8")), 66_000)
                self.assertIn(first, output)
                self.assertIn(last, output)
                self.assertIn("truncated", output)

    def test_non_newline_stream_still_honors_deadline_and_reaps_child(self):
        pid_file = self.root / "owned.pid"
        code = (
            "import os, time\n"
            f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
            "os.write(1, b'partial progress without newline')\n"
            "time.sleep(2)\n"
        )
        started = time.monotonic()
        with (
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(subprocess.TimeoutExpired) as raised,
        ):
            self.run_child(code, stream=True, timeout=0.2)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertIn(b"partial progress", raised.exception.output)
        self.assertFalse(Path(f"/proc/{pid_file.read_text()}").exists())

    def test_streamed_no_newline_flood_is_bounded_not_a_line_count_limit(self):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            result = self.run_child(
                "import os\nos.write(1, b'first:' + b'z' * 2_000_000 + b':last')\n",
                stream=True,
            )
        self.assertEqual(result.returncode, 0)
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 66_000)
        self.assertLessEqual(len(printed.getvalue().encode("utf-8")), 66_000)
        self.assertIn("first:", printed.getvalue())
        self.assertIn(":last", printed.getvalue())
        self.assertEqual(result.stderr, "")

    def test_small_results_and_utf8_at_chunk_boundaries_are_unchanged(self):
        result = self.run_child(
            "import os\n"
            "os.write(1, b'a' * 4095 + 'α中'.encode('utf-8'))\n"
            "os.write(2, 'Δ end\\n'.encode('utf-8'))\n"
        )
        self.assertEqual(result.stdout, "a" * 4095 + "α中")
        self.assertEqual(result.stderr, "Δ end\n")
        self.assertEqual(result.returncode, 0)

    def test_captured_timeout_is_bounded_and_unrelated_process_is_untouched(self):
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(10)"]
        )
        try:
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                self.run_child(
                    "import os, time\n"
                    "os.write(2, b'begin:' + b'e' * 2_000_000 + b':failure-tail')\n"
                    "time.sleep(2)\n",
                    timeout=0.3,
                )
            self.assertIsNone(unrelated.poll())
            self.assertLessEqual(len(raised.exception.stderr), 66_000)
            self.assertIn(b":failure-tail", raised.exception.stderr)
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=2)

    def test_snippet_uses_same_bound_and_retains_selected_package_bootstrap(self):
        result = env_runner.run_snippet(
            "base",
            "import os, patent_sar_extractor\n"
            "os.write(1, b'snippet-first:' + b'x' * 2_000_000 + b':snippet-last')\n",
            timeout=5,
            cwd=str(self.root),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 66_000)
        self.assertIn("snippet-first:", result.stdout)
        self.assertIn(":snippet-last", result.stdout)

    def test_parent_collection_peak_does_not_scale_with_child_output(self):
        tracemalloc.start()
        try:
            self.run_child(
                "import os\n"
                "for _ in range(1024):\n"
                "    os.write(1, b'x' * 16_384)\n"
                "    os.write(2, b'y' * 16_384)\n"
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 2_000_000, "Do not buffer the whole 32 MiB response")

    def test_sink_cancellation_reaps_exact_child_without_detaching_group(self):
        from patent_sar_extractor.core.process_capture import run_bounded

        pid_file = self.root / "cancelled.pid"
        code = (
            "import os, time\n"
            f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
            "print('cancel-here', flush=True)\n"
            "time.sleep(10)\n"
        )
        seen = []

        def cancel(line):
            pid = int(pid_file.read_text())
            seen.append(os.getpgid(pid))
            raise KeyboardInterrupt("controlled cancellation")

        with self.assertRaisesRegex(KeyboardInterrupt, "controlled cancellation"):
            run_bounded(
                [sys.executable, "-c", code],
                timeout=3,
                cwd=str(self.root),
                env=os.environ.copy(),
                on_line=cancel,
            )
        self.assertEqual(seen, [os.getpgrp()])
        self.assertFalse(Path(f"/proc/{pid_file.read_text()}").exists())

    def test_warning_split_across_reads_stays_filtered_after_middle_is_dropped(self):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            result = self.run_child(
                "import os, time\n"
                "os.write(1, b'x' * 100_000 + b'Unable to register cu')\n"
                "time.sleep(0.03)\n"
                "os.write(1, b'DNN factory' + b'y' * 100_000 + b'\\n')\n"
                "os.write(1, '正常 progress\\n'.encode('utf-8'))\n",
                stream=True,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(printed.getvalue(), "正常 progress\n")

    def test_small_streams_flush_final_partial_line_and_keep_exit_code(self):
        for code, expected, exit_code in (
            ("print('a', end=''); print('b')", "ab\n", 0),
            ("import sys; print('end', end=''); sys.exit(4)", "end", 4),
            ("pass", "", 0),
        ):
            with self.subTest(expected=expected):
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    result = self.run_child(code, stream=True)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(printed.getvalue(), expected)
                self.assertEqual(result.returncode, exit_code)

    def test_readiness_probes_use_the_same_native_interpreter_and_bound(self):
        ready = env_runner.check_env("base")
        self.assertTrue(ready["available"])
        self.assertTrue(ready["version"].startswith("Python "))
        self.assertEqual(ready["python_path"], sys.executable)
        with patch.dict(
            env_runner.ENV_REQUIRED_MODULES,
            {"base": ["json", "controlled_module_that_does_not_exist"]},
        ):
            unavailable = env_runner.check_env("base")
        self.assertFalse(unavailable["available"])
        self.assertIn("controlled_module_that_does_not_exist", unavailable["error"])


if __name__ == "__main__":
    unittest.main()
