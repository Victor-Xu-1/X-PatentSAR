"""Real bounded transport controls; not a model accuracy benchmark."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from patent_sar_extractor.web.errors import WebError


class ModelSessionTests(unittest.TestCase):
    def session(self, *, requests=5):
        from patent_sar_extractor.web.model_session import ModelSession

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        script = (
            "import json,os,sys; "
            "[(print(json.dumps({'ok':True,'result':{'pid':os.getpid(),'request':json.loads(line)}}),flush=True)) "
            "for line in sys.stdin]"
        )
        return ModelSession(
            [sys.executable, "-u", "-c", script],
            cwd=Path(self.temporary.name),
            env=dict(os.environ),
            max_requests=requests,
            max_memory_bytes=64 * 1024**2,
        )

    def test_real_requests_reuse_one_owned_process_and_close(self):
        with self.session() as session:
            a = session.exchange({"value": 1}, timeout=2)
            b = session.exchange({"value": 2}, timeout=2)
            self.assertEqual(a["pid"], b["pid"])
            self.assertEqual(b["request"], {"value": 2})
        self.assertIsNone(session.child)

    def test_controlled_recycling_creates_new_owned_process(self):
        with self.session(requests=1) as session:
            a = session.exchange({}, timeout=2)
            b = session.exchange({}, timeout=2)
            self.assertNotEqual(a["pid"], b["pid"])

    def test_cancelled_session_never_starts_model(self):
        with self.session() as session:
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(WebError):
                session.exchange({}, timeout=2, cancel=cancel)
            self.assertIsNone(session.child)
