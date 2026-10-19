"""Owned finite text calls: cancellation, identity, replay and process cleanup."""

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import numpy as np

from patent_sar_extractor.core.ocsr.worker_process import WorkerProtocolError
from patent_sar_extractor.core.text_ocr.identity import recipe
from patent_sar_extractor.core.text_ocr.process import TextOCRCancelled
from patent_sar_extractor.core.text_ocr.runtime import AuxiliaryTextRuntime

IDENTITY = {
    "fingerprint": "a" * 64,
    "model_name": "PP-OCRv6_small_rec",
    "adapter_version": "literal-row-v1",
    "device": "cpu",
}


class ControlledWorker:
    created: ClassVar[list] = []
    failure = None
    predictions = 0

    def __init__(self, command, environment):
        self.identity_only = command[-1] == "--identity"
        self.environment = environment
        self.closed = False
        self.request = None
        self.process = SimpleNamespace(
            pid=999999999, poll=lambda: 0 if self.closed else None
        )
        self.created.append(self)

    def receive(self, timeout):
        if self.identity_only:
            if self.failure == "wrong_identity":
                return dict(IDENTITY, versions={"unknown": "1"})
            return dict(
                IDENTITY,
                versions=recipe()["distributions"],
                model_revision=recipe()["model_revision"],
                model_directory=self.environment["PATENTSAR_TEXT_OCR_MODEL_DIR"],
            )
        if self.request is None:
            return {
                "status": "ready",
                "identity": dict(
                    IDENTITY,
                    versions=recipe()["distributions"],
                    model_revision=recipe()["model_revision"],
                    model_directory=self.environment["PATENTSAR_TEXT_OCR_MODEL_DIR"],
                ),
            }
        if self.failure == "timeout":
            time.sleep(min(timeout, 0.01))
            raise TimeoutError
        result = {
            key: self.request[key]
            for key in ("id", "image_sha256", "pixel_sha256", "model_fingerprint")
        }
        result.update(
            status="observed",
            text="TR-FRET",
            confidence=0.7,
            device="cpu",
            peak_rss_mb=500.0,
            confidence_kind="uncalibrated_model",
        )
        if self.failure == "wrong_id":
            result["id"] = "b" * 32
        return result

    def send(self, request):
        type(self).predictions += 1
        self.request = request

    def close(self):
        self.closed = True


class AuxiliaryTextRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.models = self.root / "models"
        self.models.mkdir()
        for name in ("inference.json", "inference.yml", "inference.pdiparams"):
            (self.models / name).write_bytes(b"controlled model identity")
        self.image = np.full((32, 150, 3), 255, np.uint8)
        self.image[10:20, 10:120] = 0
        ControlledWorker.created, ControlledWorker.predictions = [], 0
        ControlledWorker.failure = None
        self.addCleanup(patch.stopall)
        patch(
            "patent_sar_extractor.core.text_ocr.runtime.JsonLineWorker",
            ControlledWorker,
        ).start()
        patch("patent_sar_extractor.core.text_ocr.runtime.wait_for_memory").start()
        patch(
            "patent_sar_extractor.core.text_ocr.process.JsonLineWorker",
            ControlledWorker,
        ).start()
        self.reader = AuxiliaryTextRuntime(
            Path("/usr/bin/python3"), self.models, self.root
        )
        self.addCleanup(self.reader.close)

    def test_constructor_does_not_load_or_start_a_model(self):
        self.assertEqual(ControlledWorker.created, [])
        self.assertIsNone(self.reader.worker_process)

    def test_wrong_native_identity_stops_before_any_prediction(self):
        ControlledWorker.failure = "wrong_identity"
        with self.assertRaises(WorkerProtocolError):
            self.reader.observe(self.image)
        self.assertEqual(ControlledWorker.predictions, 0)
        self.assertTrue(all(w.closed for w in ControlledWorker.created))

    def test_cache_is_exact_pixel_model_bound_and_independently_mutable(self):
        result = self.reader.observe(self.image)
        self.assertFalse(result["cache_hit"])
        self.assertEqual(result["confidence"], 0.7)
        self.assertNotIn("accepted", result)
        result["text"] = "changed by consumer"
        again = self.reader.observe(self.image)
        self.assertTrue(again["cache_hit"])
        self.assertEqual(again["text"], "TR-FRET")
        self.assertEqual(ControlledWorker.predictions, 1)
        different = self.image.copy()
        different[10, 10] = 255
        self.assertFalse(self.reader.observe(different)["cache_hit"])
        self.assertEqual(ControlledWorker.predictions, 2)

    def test_model_change_discards_old_cached_observations(self):
        self.reader.observe(self.image)
        old = self.reader._worker
        (self.models / "inference.yml").write_bytes(b"changed model")
        result = self.reader.observe(self.image)
        self.assertTrue(old.closed)
        self.assertFalse(result["cache_hit"])
        self.assertEqual(ControlledWorker.predictions, 2)

    def test_wrong_response_is_not_cached_or_automatically_replayed(self):
        ControlledWorker.failure = "wrong_id"
        with self.assertRaises(ValueError):
            self.reader.observe(self.image)
        self.assertTrue(all(w.closed for w in ControlledWorker.created))
        self.assertEqual(ControlledWorker.predictions, 1)
        self.assertEqual(len(self.reader._cache), 0)
        self.assertEqual(list(self.reader.root.glob("*.png")), [])

    def test_cancel_before_start_performs_no_native_work(self):
        event = threading.Event()
        event.set()
        self.reader.cancel = event
        with self.assertRaises(TextOCRCancelled):
            self.reader.observe(self.image)
        self.assertEqual(ControlledWorker.created, [])

    def test_cancel_between_requests_closes_existing_model_before_cache_hit(self):
        self.reader.observe(self.image)
        self.reader.cancel = threading.Event()
        self.reader.cancel.set()
        with self.assertRaises(TextOCRCancelled):
            self.reader.observe(self.image)
        self.assertTrue(all(w.closed for w in ControlledWorker.created))

    def test_cancel_during_request_closes_its_owned_worker(self):
        self.reader.cancel = threading.Event()
        ControlledWorker.failure = "timeout"
        timer = threading.Timer(0.05, self.reader.cancel.set)
        timer.start()
        self.addCleanup(timer.join)
        with self.assertRaises(TextOCRCancelled):
            self.reader.observe(self.image)
        self.assertTrue(all(w.closed for w in ControlledWorker.created))

    def test_two_failures_exhaust_without_unbounded_restarts(self):
        ControlledWorker.failure = "wrong_id"
        for _ in range(2):
            with self.assertRaises(ValueError):
                self.reader.observe(self.image)
        count = len(ControlledWorker.created)
        with self.assertRaises(WorkerProtocolError):
            self.reader.observe(self.image)
        self.assertEqual(len(ControlledWorker.created), count)

    def test_deadline_includes_waiting_for_the_serial_owner(self):
        self.reader._lock.acquire()
        try:
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                self.reader.observe(self.image, timeout=1)
            self.assertLess(time.monotonic() - start, 1.3)
            self.assertEqual(ControlledWorker.created, [])
        finally:
            self.reader._lock.release()

    def test_child_cannot_inherit_parent_credentials_or_python_paths(self):
        self.reader.observe(self.image)
        child = ControlledWorker.created[-1]
        for key in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "PYTHONPATH",
            "HTTPS_PROXY",
            "LD_LIBRARY_PATH",
        ):
            self.assertNotIn(key, child.environment)
        self.assertEqual(child.environment["CUDA_VISIBLE_DEVICES"], "-1")

    def test_close_releases_the_owned_process_and_private_row_workspace(self):
        self.reader.observe(self.image)
        root = self.reader.root
        self.reader.close()
        self.assertFalse(root.exists())
        self.assertTrue(all(w.closed for w in ControlledWorker.created))
        with self.assertRaises(WorkerProtocolError):
            self.reader.observe(self.image)
