"""The auxiliary reader cannot turn arbitrary files/output into source evidence."""

import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from patent_sar_extractor.core.text_ocr.protocol import (
    MAX_PIXELS,
    frame_digest,
    read_frame,
    validate_reply,
)


class AuxiliaryTextProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.image = np.full((32, 160, 3), 255, np.uint8)
        self.image[10:20, 20:120] = 0
        self.path = self.root / "row.png"
        Image.fromarray(self.image).save(self.path)
        self.request = {
            "id": "a" * 32,
            "image_path": str(self.path),
            "image_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "pixel_sha256": frame_digest(self.image),
            "shape": list(self.image.shape),
            "model_fingerprint": "b" * 64,
        }

    def test_exact_complete_row_is_preserved(self):
        actual = read_frame(self.request, self.root, "b" * 64)
        self.assertTrue(np.array_equal(actual, self.image))

    def test_unknown_fields_and_wrong_owner_are_refused(self):
        for change in (
            {"other": 1},
            {"id": "bad"},
            {"model_fingerprint": "c" * 64},
            {"shape": [32, 159, 3]},
            {"pixel_sha256": "d" * 64},
            {"image_sha256": "e" * 64},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                read_frame(dict(self.request, **change), self.root, "b" * 64)

    def test_outside_and_symlink_inputs_are_refused_before_decode(self):
        with tempfile.TemporaryDirectory() as other:
            path = Path(other) / "row.png"
            Image.fromarray(self.image).save(path)
            with self.assertRaises(ValueError):
                read_frame(
                    dict(self.request, image_path=str(path)), self.root, "b" * 64
                )
        link = self.root / "linked.png"
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            read_frame(dict(self.request, image_path=str(link)), self.root, "b" * 64)

    def test_dimensions_and_dtype_cannot_hide_a_page(self):
        for image in (
            np.zeros((257, 5, 3), np.uint8),
            np.zeros((2, 4097, 3), np.uint8),
            np.zeros((32, 160), np.uint8),
            self.image.astype(float),
            np.zeros((256, MAX_PIXELS // 256 + 1, 3), np.uint8),
        ):
            with self.subTest(shape=image.shape), self.assertRaises(ValueError):
                frame_digest(image)

    def test_empty_text_is_an_observation_not_a_scientific_success(self):
        reply = self.reply()
        reply.update(text="", confidence=0.0)
        self.assertEqual(validate_reply(reply, self.request)["text"], "")
        self.assertNotIn("accepted", validate_reply(reply, self.request))

    def test_invalid_scores_and_unowned_responses_are_refused(self):
        for change in (
            {"confidence": True},
            {"confidence": float("nan")},
            {"confidence": 1.01},
            {"text": "x" * 4097},
            {"model_fingerprint": "c" * 64},
            {"id": "z" * 32},
            {"pixel_sha256": "c" * 64},
            {"peak_rss_mb": 1025},
            {"accepted": True},
            {"confidence_kind": "calibrated"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_reply(dict(self.reply(), **change), self.request)

    def reply(self):
        return {
            key: self.request[key]
            for key in ("id", "image_sha256", "pixel_sha256", "model_fingerprint")
        } | {
            "status": "observed",
            "text": "IC50 (nM)",
            "confidence": 0.99,
            "device": "cpu",
            "peak_rss_mb": 512.0,
            "confidence_kind": "uncalibrated_model",
        }
