"""Exercise the actual bounded JSONL subprocess protocol without a model SDK."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.core.ocsr.engines.decimer_engine import DECIMEREngine


class DecimerProcessTests(unittest.TestCase):
    def setUp(self):
        # These real subprocesses are protocol controls, not SDK/model loads.
        headroom = patch(
            "patent_sar_extractor.core.ocsr.engines.decimer_engine.wait_for_memory"
        )
        headroom.start()
        self.addCleanup(headroom.stop)

    def engine(self, root: Path, behavior: str = "success"):
        script = root / "worker.py"
        script.write_text(
            "import json,sys,time,os\n"
            "identity={'fingerprint':'a'*64,'versions':{'DECIMER':'2.8.0'}}\n"
            "if '--identity' in sys.argv:\n"
            " print(json.dumps(identity),flush=True);sys.exit(0)\n"
            "print(json.dumps({'status':'ready','identity':identity,'device':'cpu'}),flush=True)\n"
            "for line in sys.stdin:\n"
            " r=json.loads(line)\n"
            + (
                " sys.stdout.write('{');sys.stdout.flush();time.sleep(10)\n"
                if behavior == "partial"
                else " print('x'*70000,flush=True)\n"
                if behavior == "oversized"
                else " print(json.dumps({'id':'wrong','status':'success','smiles':'CCO'}),flush=True)\n"
                if behavior == "wrong_id"
                else " print(json.dumps({'id':r['id'],'status':'success','smiles':'CCO','model_fingerprint':'a'*64,'peak_rss_mb':10}),flush=True)\n"
            ),
            encoding="utf-8",
        )
        image = root / "image.png"
        image.write_bytes(b"controlled protocol input")
        return DECIMEREngine(
            python_bin=sys.executable, batch_wrapper_script=str(script)
        ), image

    def test_reuses_one_actual_process_and_reaps_it_on_close(self):
        with tempfile.TemporaryDirectory() as temp:
            engine, image = self.engine(Path(temp))
            self.addCleanup(engine.close)
            first = engine.predict(str(image), timeout=2)
            process = engine.worker_process
            second = engine.predict(str(image), timeout=2)
            self.assertEqual(first["raw_smiles"], "CCO")
            self.assertEqual(second["model_fingerprint"], "a" * 64)
            self.assertIs(engine.worker_process, process)
            engine.close()
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdout.closed)
            self.assertTrue(process.stderr.closed)

    def test_partial_line_obeys_deadline_and_does_not_spawn_single_image_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            engine, image = self.engine(Path(temp), "partial")
            self.addCleanup(engine.close)
            started = time.monotonic()
            result = engine.predict(str(image), timeout=0.15)
            self.assertEqual(result["status"], "timeout")
            self.assertLess(time.monotonic() - started, 2)
            self.assertIsNone(engine.worker_process)

    def test_oversized_and_mismatched_packets_fail_closed(self):
        for behavior in ("oversized", "wrong_id"):
            with self.subTest(behavior=behavior), tempfile.TemporaryDirectory() as temp:
                engine, image = self.engine(Path(temp), behavior)
                self.addCleanup(engine.close)
                result = engine.predict(str(image), timeout=2)
                self.assertEqual(result["status"], "failed")
                self.assertIsNone(engine.worker_process)

    def test_missing_batch_worker_is_not_available(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = DECIMEREngine(
                python_bin=sys.executable,
                batch_wrapper_script=str(Path(temp) / "missing.py"),
            )
            self.assertFalse(engine.is_available())

    def test_healthy_window_recycles_without_spending_failure_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            engine, image = self.engine(Path(temp))
            self.addCleanup(engine.close)
            self.assertEqual(engine.predict(str(image), timeout=2)["status"], "success")
            original = engine.worker_process
            engine._requests = 100
            self.assertEqual(engine.predict(str(image), timeout=2)["status"], "success")
            self.assertIsNot(engine.worker_process, original)
            self.assertIsNotNone(original.poll())
            self.assertFalse(engine.session_exhausted)

    def test_cpu_policy_is_explicit_and_parent_pythonpath_is_not_inherited(self):
        with patch.dict(
            os.environ,
            {
                "PYTHONPATH": "/untrusted/parent",
                "PATENTSAR_DECIMER_ENABLE_GPU": "0",
                "CUDA_VISIBLE_DEVICES": "0",
            },
        ):
            environment = DECIMEREngine()._build_env()
        self.assertNotIn("PYTHONPATH", environment)
        self.assertEqual(environment["CUDA_VISIBLE_DEVICES"], "-1")

    def test_explicit_worker_policy_is_used_for_identity_and_execution(self):
        policy = {
            "PATENTSAR_DECIMER_ENABLE_GPU": "0",
            "PATENTSAR_DECIMER_CPU_THREADS": "3",
        }
        with patch.dict(os.environ, {"PATENTSAR_DECIMER_ENABLE_GPU": "1"}):
            engine = DECIMEREngine(env_extra=policy)
            policy["PATENTSAR_DECIMER_ENABLE_GPU"] = "1"
            with patch(
                "patent_sar_extractor.core.ocsr.engines.decimer_engine.query_identity",
                return_value={"fingerprint": "a" * 64},
            ) as identity:
                engine.runtime_identity()
            identity_environment = identity.call_args.args[2]
            self.assertEqual(identity_environment, engine._build_env())
            self.assertEqual(identity_environment["PATENTSAR_DECIMER_ENABLE_GPU"], "0")
            self.assertEqual(identity_environment["PATENTSAR_DECIMER_CPU_THREADS"], "3")


if __name__ == "__main__":
    unittest.main()
