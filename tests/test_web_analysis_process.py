"""Real child processes test the protocol, timeout, cancellation and ownership."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from test_web_support import WebFixture

from patent_sar_extractor.web.analysis_children import alive, read_child
from patent_sar_extractor.web.analysis_process import BoundedAnalysisRunner
from patent_sar_extractor.web.analysis_runtime import (
    AnalysisSettings,
    child_environment,
)
from patent_sar_extractor.web.errors import WebError


class ProcessTests(WebFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.runner = BoundedAnalysisRunner()
        self.addCleanup(self.runner.close)
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.addCleanup(self.pool.shutdown, wait=True)

    def run_code(self, code, payload=None, timeout=3, cancel=None):
        return self.runner.run(
            [sys.executable, "-I", "-c", code],
            payload or {},
            cwd=self.root,
            env=child_environment(AnalysisSettings(), Path(sys.executable), self.root),
            timeout=timeout,
            cancel=cancel,
        )

    def wait_file(self, name):
        deadline = time.monotonic() + 3
        path = self.root / name
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(path.is_file())
        return path

    def test_actual_json_protocol_and_environment_allowlist(self):
        code = "import json,sys,os; d=json.load(sys.stdin); print(json.dumps({'ok':True,'result':{'echo':d,'threads':os.environ['OMP_NUM_THREADS'],'gpu':os.environ['CUDA_VISIBLE_DEVICES'],'keys':sorted(os.environ)}}))"
        result = self.run_code(code, {"smiles": ["CCO"]})
        self.assertEqual(result["echo"], {"smiles": ["CCO"]})
        self.assertEqual(result["threads"], "1")
        self.assertEqual(result["gpu"], "-1")
        self.assertNotIn("LLM_API_KEY", result["keys"])
        self.assertNotIn("HTTPS_PROXY", result["keys"])

    def test_malformed_nonfinite_utf8_nonzero_and_large_output_fail_closed(self):
        cases = [
            ("print('not-json')", "analysis_protocol"),
            ('print(\'{"ok":true,"result":{"value":NaN}}\')', "analysis_protocol"),
            ("import os;os.write(1,b'\\xff')", "analysis_protocol"),
            ("raise SystemExit(7)", "analysis_worker_failed"),
            ("print('x'*1100000)", "analysis_output_limit"),
            ("import sys;sys.stderr.write('x'*300000)", "analysis_output_limit"),
            (
                'print(\'{"ok":false,"code":"runtime_unavailable"}\')',
                "analysis_environment_unavailable",
            ),
        ]
        for code, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(WebError) as error:
                self.run_code(code)
            self.assertEqual(error.exception.code, expected)
            self.assertNotIn("Traceback", error.exception.message)

    def test_timeout_and_nonreading_stdin_do_not_block(self):
        began = time.monotonic()
        with self.assertRaises(WebError) as error:
            self.run_code(
                "import time;time.sleep(20)", {"large": "x" * 100000}, timeout=0.15
            )
        self.assertEqual(error.exception.code, "analysis_timeout")
        self.assertLess(time.monotonic() - began, 2)
        self.assertEqual(self.run_code('print(\'{"ok":true,"result":{}}\')'), {})

    def test_shared_busy_gate_cancel_and_unrelated_process_survives(self):
        unrelated = subprocess.Popen(
            [sys.executable, "-I", "-c", "import time;time.sleep(30)"]
        )
        self.addCleanup(unrelated.wait)
        self.addCleanup(unrelated.kill)
        cancel = threading.Event()
        future = self.pool.submit(
            self.run_code,
            "import pathlib,os,time;pathlib.Path('owned.pid').write_text(str(os.getpid()));time.sleep(30)",
            timeout=10,
            cancel=cancel,
        )
        pid = int(self.wait_file("owned.pid").read_text())
        child = read_child(pid)
        with self.assertRaises(WebError) as busy:
            self.run_code('print(\'{"ok":true,"result":{}}\')')
        self.assertEqual(busy.exception.code, "analysis_busy")
        cancel.set()
        with self.assertRaises(WebError) as error:
            future.result(timeout=3)
        self.assertEqual(error.exception.code, "analysis_cancelled")
        self.assertIsNotNone(child)
        self.assertFalse(alive(child))
        self.assertIsNone(unrelated.poll())

    def test_close_stops_owned_detached_descendant_and_reaps_parent(self):
        code = (
            "import subprocess,sys,pathlib,os,time; "
            "p=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(30)'],start_new_session=True); "
            "pathlib.Path('descendant.pid').write_text(str(p.pid)); "
            "pathlib.Path('parent.pid').write_text(str(os.getpid())); time.sleep(30)"
        )
        future = self.pool.submit(self.run_code, code, timeout=10)
        parent = read_child(int(self.wait_file("parent.pid").read_text()))
        descendant = read_child(int(self.wait_file("descendant.pid").read_text()))
        time.sleep(
            0.2
        )  # Allow the kernel-parent observation, not a model timing assumption.
        self.runner.close()
        with self.assertRaises(WebError):
            future.result(timeout=3)
        self.assertFalse(alive(parent))
        self.assertFalse(alive(descendant))
        self.assertFalse((self.root / "web-process.log").exists())
        with self.assertRaises(WebError):
            self.run_code('print(\'{"ok":true,"result":{}}\')')

    def test_bounded_input_and_invalid_timeouts_never_start_child(self):
        for timeout in (0, 181, float("inf")):
            with self.assertRaises(WebError):
                self.run_code("raise SystemExit(99)", timeout=timeout)
        with self.assertRaises(WebError) as error:
            self.run_code("raise SystemExit(99)", {"oversized": "x" * 140000})
        self.assertEqual(error.exception.code, "analysis_input_limit")
