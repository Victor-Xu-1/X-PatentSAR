"""Native text request packets cannot create an idle or partial-input service."""

import json
import os
import time
import unittest

from patent_sar_extractor.core.text_ocr.request_stream import request_packets


class AuxiliaryTextRequestTests(unittest.TestCase):
    def pipe(self, payload, *, close=True):
        read, write = os.pipe()
        stream = os.fdopen(read, "rb", buffering=0)
        self.addCleanup(stream.close)
        if payload:
            os.write(write, payload)
        if close:
            os.close(write)
        else:
            self.addCleanup(os.close, write)
        return stream

    def test_multiple_complete_packets_remain_separate(self):
        rows = [{"id": "first"}, {"id": "second"}]
        data = b"".join(json.dumps(r).encode() + b"\n" for r in rows)
        self.assertEqual(list(request_packets(self.pipe(data))), rows)

    def test_idle_worker_returns_without_any_inference(self):
        started = time.monotonic()
        self.assertEqual(
            list(request_packets(self.pipe(b"", close=False), idle_seconds=0.02)), []
        )
        self.assertLess(time.monotonic() - started, 0.2)

    def test_partial_packet_has_its_own_deadline(self):
        for close in (False, True):
            with self.subTest(close=close), self.assertRaises(ValueError):
                list(
                    request_packets(
                        self.pipe(b'{"id":', close=close), idle_seconds=0.02
                    )
                )

    def test_oversize_nonfinite_and_nonobjects_are_refused(self):
        for payload in (b"x" * 4096, b"x" * 4096 + b"\n", b'{"score": NaN}\n'):
            with self.subTest(size=len(payload)), self.assertRaises(ValueError):
                list(request_packets(self.pipe(payload)))
        with self.assertRaises(TypeError):
            list(request_packets(self.pipe(b"[]\n")))

    def test_request_budget_is_explicit_and_finite(self):
        stream = self.pipe(b'{"id":1}\n{"id":2}\n')
        self.assertEqual(list(request_packets(stream, maximum=1)), [{"id": 1}])
