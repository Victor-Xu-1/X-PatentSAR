"""Virtual-clock worker controls; no native model or user document is loaded."""

import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from patent_sar_extractor.core.ocsr.worker_process import WorkerProtocolError
from patent_sar_extractor.core.text_ocr.process import (
    TextOCRCancelled,
    TextOCRPhaseTimeout,
)
from patent_sar_extractor.core.text_ocr.runtime import AuxiliaryTextRuntime
from tests import test_auxiliary_text_runtime as controlled


class VirtualWorkerClock:
    def __init__(self, delays=None, callback=None):
        self.seconds = 0.0
        self.delays = delays or {
            "identity": 12,
            "worker_ready": 6,
            "prepare": 26,
            "observe": 18,
        }
        self.callback = callback

    def receive(self, worker, deadline, cancel):
        phase = (
            "identity"
            if worker.identity_only
            else "worker_ready"
            if worker.request is None
            else worker.operation
        )
        self.seconds += self.delays.get(phase, 0)
        if self.callback:
            self.callback(worker, phase)
        if self.seconds >= deadline:
            raise TimeoutError("Controlled finite phase exceeded its budget")
        return worker.receive(0)


@contextmanager
def virtual_calls(delays=None, callback=None):
    clock = VirtualWorkerClock(delays, callback)
    with (
        patch("time.monotonic", side_effect=lambda: clock.seconds),
        patch("patent_sar_extractor.core.text_ocr.runtime.receive", clock.receive),
        patch("patent_sar_extractor.core.text_ocr.process.receive", clock.receive),
    ):
        yield clock


class AuxiliaryTextStartupTests(unittest.TestCase):
    def setUp(self):
        self.fixture = controlled.AuxiliaryTextRuntimeTests(
            "test_constructor_does_not_load_or_start_a_model"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_cold_activation_and_prediction_have_separate_finite_budgets(self):
        with virtual_calls() as clock:
            observed = self.fixture.reader.observe(self.fixture.image, timeout=30)
            self.assertEqual(observed["text"], "TR-FRET")
            self.assertEqual(observed["confidence"], 0.7)
            self.assertEqual(clock.seconds, 62)
            self.assertTrue(
                self.fixture.reader.observe(self.fixture.image)["cache_hit"]
            )
            self.assertEqual(clock.seconds, 62)
            other = self.fixture.image.copy()
            other[10, 10] = 255
            self.assertFalse(self.fixture.reader.observe(other)["cache_hit"])
            self.assertEqual(clock.seconds, 80)
        self.assertEqual(controlled.ControlledWorker.predictions, 2)
        self.assertEqual(controlled.ControlledWorker.preparations, 1)

    def test_each_slow_phase_refuses_with_its_own_code_and_no_partial_cache(self):
        for delays, phase in (
            ({"identity": 61}, "identity"),
            ({"identity": 12, "worker_ready": 49}, "worker_ready"),
            ({"identity": 12, "worker_ready": 6, "prepare": 43}, "model_prepare"),
            ({"observe": 31}, "inference"),
        ):
            with (
                self.subTest(phase=phase),
                AuxiliaryTextRuntime(
                    Path("/usr/bin/python3"), self.fixture.models, self.fixture.root
                ) as reader,
            ):
                with (
                    virtual_calls(delays),
                    self.assertRaises(TextOCRPhaseTimeout) as raised,
                ):
                    reader.observe(self.fixture.image)
                self.assertEqual(raised.exception.phase, phase)
                self.assertEqual(raised.exception.code, phase + "_timeout")
                self.assertIsNone(reader.worker_process)
                self.assertFalse(reader._model_prepared)
                self.assertEqual(len(reader._cache), 0)
                self.assertEqual(list(reader.root.glob("*.png")), [])

    def test_forged_prepare_or_old_transport_never_reaches_prediction(self):
        for failure in (
            "old_protocol",
            "bad_prepare_id",
            "bad_prepare_fingerprint",
            "bad_prepare_fields",
        ):
            controlled.ControlledWorker.failure = failure
            with (
                self.subTest(failure=failure),
                AuxiliaryTextRuntime(
                    Path("/usr/bin/python3"), self.fixture.models, self.fixture.root
                ) as reader,
            ):
                with self.assertRaises((WorkerProtocolError, ValueError)):
                    reader.observe(self.fixture.image)
                self.assertEqual(reader._total, 0)
                self.assertIsNone(reader.worker_process)
                self.assertFalse(reader._model_prepared)
        self.assertEqual(controlled.ControlledWorker.predictions, 0)

    def test_cancel_after_prepare_ack_stops_before_inference(self):
        reader = self.fixture.reader
        reader.cancel = threading.Event()

        def cancel(worker, phase):
            if phase == "prepare":
                reader.cancel.set()

        with virtual_calls(callback=cancel), self.assertRaises(TextOCRCancelled):
            reader.observe(self.fixture.image)
        self.assertEqual(controlled.ControlledWorker.predictions, 0)
        self.assertIsNone(reader.worker_process)
        self.assertFalse(reader._model_prepared)

    def test_model_change_during_activation_refuses_before_inference(self):
        def changed(worker, phase):
            if phase == "prepare":
                (self.fixture.models / "inference.yml").write_bytes(
                    b"Changed during model activation"
                )

        with virtual_calls(callback=changed), self.assertRaises(WorkerProtocolError):
            self.fixture.reader.observe(self.fixture.image)
        self.assertEqual(controlled.ControlledWorker.predictions, 0)
        self.assertIsNone(self.fixture.reader.worker_process)

    def test_preparation_consumes_the_existing_wire_budget_and_new_worker_is_cold(self):
        reader = self.fixture.reader
        reader.observe(self.fixture.image)
        previous = reader._worker
        self.assertEqual(reader._requests, 2)
        reader._requests = 256
        changed = self.fixture.image.copy()
        changed[10, 10] = 255
        reader.observe(changed)
        self.assertTrue(previous.closed)
        self.assertEqual(reader._requests, 2)
        self.assertEqual(controlled.ControlledWorker.preparations, 2)
        self.assertEqual(controlled.ControlledWorker.predictions, 2)

    def test_failed_inference_is_charged_to_the_same_session_limit(self):
        reader = self.fixture.reader
        controlled.ControlledWorker.failure = "wrong_id"
        with self.assertRaises(ValueError):
            reader.observe(self.fixture.image)
        self.assertEqual(reader._total, 1)
        reader._total = 2048
        count = len(controlled.ControlledWorker.created)
        controlled.ControlledWorker.failure = None
        with self.assertRaises(WorkerProtocolError):
            reader.observe(self.fixture.image)
        self.assertEqual(len(controlled.ControlledWorker.created), count)
        self.assertEqual(controlled.ControlledWorker.predictions, 1)

    def test_idle_rotation_prepares_once_but_an_exact_cache_hit_starts_nothing(self):
        reader = self.fixture.reader
        with virtual_calls() as clock:
            reader.observe(self.fixture.image)
            previous = reader._worker
            clock.seconds += 31
            self.assertTrue(reader.observe(self.fixture.image)["cache_hit"])
            self.assertIs(reader._worker, previous)
            self.assertEqual(controlled.ControlledWorker.preparations, 1)
            changed = self.fixture.image.copy()
            changed[10, 10] = 255
            self.assertFalse(reader.observe(changed)["cache_hit"])
            self.assertTrue(previous.closed)
            self.assertEqual(controlled.ControlledWorker.preparations, 2)
            self.assertEqual(controlled.ControlledWorker.predictions, 2)

    def test_queued_timeout_does_not_close_the_current_owners_prepared_worker(self):
        reader = self.fixture.reader
        reader.observe(self.fixture.image)
        previous = reader._worker
        reader._lock.acquire()
        try:
            with self.assertRaises(TextOCRPhaseTimeout) as raised:
                reader.observe(self.fixture.image, timeout=1)
            self.assertEqual(raised.exception.phase, "queue")
            self.assertIs(reader._worker, previous)
            self.assertFalse(previous.closed)
            self.assertTrue(reader._model_prepared)
        finally:
            reader._lock.release()

    def test_slow_source_preparation_cannot_reset_an_expired_startup_budget(self):
        original_save = Image.Image.save
        with virtual_calls({"identity": 0}) as clock:

            def slow_save(image, *args, **kwargs):
                clock.seconds += 61
                return original_save(image, *args, **kwargs)

            with (
                patch.object(Image.Image, "save", slow_save),
                self.assertRaises(TextOCRPhaseTimeout) as raised,
            ):
                self.fixture.reader.observe(self.fixture.image)
        self.assertEqual(raised.exception.phase, "source_frame")
        self.assertEqual(controlled.ControlledWorker.preparations, 0)
        self.assertEqual(controlled.ControlledWorker.predictions, 0)
        self.assertEqual(list(self.fixture.reader.root.glob("*.png")), [])


if __name__ == "__main__":
    unittest.main()
