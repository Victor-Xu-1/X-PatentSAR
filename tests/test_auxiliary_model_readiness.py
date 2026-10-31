"""Actual owned-row validation and controlled SDK; no native model is loaded."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from patent_sar_extractor.core.text_ocr import model as model_module
from patent_sar_extractor.core.text_ocr.control import (
    WORKER_PROTOCOL_VERSION,
    control_packet,
    parse_control,
    prepared_reply,
    validate_prepared,
    worker_ready_matches,
)
from patent_sar_extractor.core.text_ocr.protocol import frame_digest, validate_reply


class AuxiliaryModelReadinessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.image = np.full((32, 150, 3), 255, np.uint8)
        self.image[10:20, 10:120] = [14, 33, 77]
        self.path = self.root / "owned.png"
        Image.fromarray(self.image).save(self.path)
        self.request = {
            "id": "1" * 32,
            "image_path": str(self.path),
            "image_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "pixel_sha256": frame_digest(self.image),
            "shape": list(self.image.shape),
            "model_fingerprint": "a" * 64,
        }
        self.identity = {
            "fingerprint": "a" * 64,
            "model_directory": str(self.root),
            "model_name": "PP-OCRv6_small_rec",
        }
        self.created, self.predictions = [], []

        def predict(*, input, batch_size):
            self.predictions.append((input.copy(), batch_size))
            return [{"rec_text": "Original literal", "rec_score": 0.7}]

        def create(**settings):
            self.created.append(settings)
            return SimpleNamespace(predict=predict)

        self.addCleanup(patch.stopall)
        patch.dict(
            "sys.modules", {"paddleocr": SimpleNamespace(TextRecognition=create)}
        ).start()
        patch.object(model_module, "model_files", return_value=[]).start()
        self.model = model_module.LiteralTextModel(self.identity, self.root)

    def test_constructor_and_unprepared_inference_never_load_the_sdk(self):
        self.assertEqual(self.created, [])
        with self.assertRaises(ValueError):
            self.model.observe(self.request)
        self.assertEqual(self.created, [])
        self.assertEqual(self.predictions, [])

    def test_prepare_validates_original_row_then_only_loads_once_without_predicting(
        self,
    ):
        ready = self.model.prepare(self.request)
        validate_prepared(ready, self.request)
        with self.assertRaises(ValueError):
            validate_reply(ready, self.request)
        self.model.prepare(self.request)
        self.assertEqual(len(self.created), 1)
        self.assertEqual(self.predictions, [])
        settings = self.created[0]
        self.assertEqual(settings["device"], "cpu")
        self.assertEqual(settings["cpu_threads"], 2)
        self.assertFalse(settings["enable_mkldnn"])
        self.assertFalse(settings["enable_hpi"])
        observed = self.model.observe(self.request)
        self.assertEqual(observed["text"], "Original literal")
        self.assertEqual(observed["confidence"], 0.7)
        self.assertNotIn("accepted", observed)
        self.assertEqual(len(self.predictions), 1)
        np.testing.assert_array_equal(self.predictions[0][0], self.image[:, :, ::-1])

    def test_invalid_original_frame_cannot_activate_a_model(self):
        for field, value in (
            ("image_path", str(self.root.parent / "outside.png")),
            ("image_sha256", "0" * 64),
            ("model_fingerprint", "b" * 64),
            ("shape", [257, 150, 3]),
            ("extra", True),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.model.prepare({**self.request, field: value})
        self.assertEqual(self.created, [])
        self.assertEqual(self.predictions, [])

    def test_changed_row_after_prepare_is_refused_before_prediction(self):
        self.model.prepare(self.request)
        changed = self.image.copy()
        changed[10, 10] = 255
        Image.fromarray(changed).save(self.path)
        with self.assertRaises(ValueError):
            self.model.observe(self.request)
        self.assertEqual(self.predictions, [])

    def test_control_and_readiness_packets_are_strict_not_scientific_observations(self):
        for operation in ("prepare", "observe"):
            packet = control_packet(operation, self.request)
            self.assertEqual(parse_control(packet), (operation, self.request))
        for packet in (
            self.request,
            {"operation": "unknown", "request": self.request},
            {"operation": [], "request": self.request},
            {"operation": "prepare", "request": [], "extra": 1},
        ):
            with (
                self.subTest(packet=packet),
                self.assertRaises((TypeError, ValueError)),
            ):
                parse_control(packet)
        ready = {
            "status": "worker_ready",
            "protocol_version": WORKER_PROTOCOL_VERSION,
            "identity": self.identity,
        }
        self.assertTrue(worker_ready_matches(ready, self.identity))
        for version in (True, 2.0, "2", 1, None):
            self.assertFalse(
                worker_ready_matches(
                    {**ready, "protocol_version": version}, self.identity
                )
            )
        prepared = prepared_reply(self.request)
        for field, value in (
            ("status", "observed"),
            ("id", "b" * 32),
            ("model_fingerprint", "b" * 64),
            ("text", "injected"),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_prepared({**prepared, field: value}, self.request)


if __name__ == "__main__":
    unittest.main()
