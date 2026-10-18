"""Shared SDK regressions using controlled rasters, never private patent inputs."""

import copy
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from patent_sar_extractor.core.cell_header_lines import (
    observe_header_lines,
    physical_line_frame,
)
from patent_sar_extractor.core.page_ocr_cache import get_ocr_engine
from patent_sar_extractor.core.rapidocr_adapter import source_canvas


class SourceCanvasGeometryTests(unittest.TestCase):
    def test_only_collapsing_shapes_receive_trailing_white_pixels(self):
        for h, w in ((1, 5000), (25, 5000), (5000, 1), (5000, 25)):
            with self.subTest(height=h, width=w):
                image = np.arange(h * w * 3, dtype=np.uint8).reshape(h, w, 3)
                before = image.copy()
                image.flags.writeable = False
                padded = source_canvas(image, 2000)
                self.assertEqual(padded.shape, (max(h, 44), max(w, 44), 3))
                np.testing.assert_array_equal(padded[:h, :w], before)
                np.testing.assert_array_equal(image, before)
                self.assertTrue(np.all(padded[h:, :] == 255))
                self.assertTrue(np.all(padded[:, w:] == 255))

    def test_all_ordinary_inputs_remain_the_identical_object(self):
        # A valid whole-page raster is not subject to the *additional* padding
        # budget. It does not allocate a second canvas or change source pixels.
        for h, w in ((10, 1000), (43, 5000), (5000, 43), (300, 600), (3000, 3000)):
            with self.subTest(height=h, width=w):
                image = np.full((h, w, 3), 255, dtype=np.uint8)
                self.assertIs(source_canvas(image, 2000), image)

    def test_sdk_quantization_boundary_and_configured_limits(self):
        from rapidocr_onnxruntime.utils.process_img import (
            ResizeImgError,
            reduce_max_side,
        )

        for limit in (32, 33, 64, 1000, 2000):
            for transpose in (False, True):
                with self.subTest(limit=limit, transpose=transpose):
                    h, w = (1, limit * 2 + 7)
                    if transpose:
                        h, w = w, h
                    image = np.zeros((h, w, 3), dtype=np.uint8)
                    with self.assertRaises(ResizeImgError):
                        reduce_max_side(image, limit)
                    padded = source_canvas(image, limit)
                    result, rh, rw = reduce_max_side(padded, limit)
                    self.assertGreater(min(result.shape[:2]), 0)
                    self.assertGreater(rh, 0)
                    self.assertGreater(rw, 0)

        for h, collapsed in (
            (40, True),
            (41, True),
            (42, True),
            (43, False),
            (44, False),
        ):
            image = np.zeros((h, 5000, 3), dtype=np.uint8)
            with self.subTest(height=h):
                self.assertEqual(source_canvas(image, 2000) is not image, collapsed)

    def test_padding_is_bounded_without_dropping_or_resampling_source(self):
        from patent_sar_extractor.core.rapidocr_adapter import MAX_PADDED_PIXELS

        below = np.zeros((1, 30000, 3), dtype=np.uint8)
        padded = source_canvas(below, 2000)
        self.assertLessEqual(padded.shape[0] * padded.shape[1], MAX_PADDED_PIXELS)
        np.testing.assert_array_equal(padded[:1], below)
        for shape in ((1, 32000, 3), (32000, 1, 3)):
            with (
                self.subTest(shape=shape),
                self.assertRaisesRegex(ValueError, "bounded padding"),
            ):
                source_canvas(np.zeros(shape, dtype=np.uint8), 2000)

    def test_malformed_inputs_and_impossible_sdk_limits_are_explicit(self):
        for image in (
            None,
            np.zeros((3, 3)),
            np.zeros((3, 3, 4), dtype=np.uint8),
            np.zeros((0, 3, 3), dtype=np.uint8),
            np.zeros((3, 3, 3)),
        ):
            with self.subTest(image_type=type(image)), self.assertRaises(ValueError):
                source_canvas(image, 2000)
        for limit in (None, True, 0, 16, 31, 2000.0, "2000"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                source_canvas(np.zeros((1, 5000, 3), dtype=np.uint8), limit)


class RapidOCRSourceCanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        kind, cls.engine = get_ocr_engine()
        if kind != "rapidocr":
            raise AssertionError(
                "These controlled checks require the installed RapidOCR"
            )

    def test_shared_engine_reads_long_thin_rasters_without_mutating_source(self):
        for h, w in ((1, 5000), (25, 5000), (5000, 1), (5000, 25)):
            with self.subTest(height=h, width=w):
                image = np.full((h, w, 3), 255, dtype=np.uint8)
                image[h // 2, :, :] = 0
                before = image.copy()
                result, _ = self.engine(image, use_det=False, use_cls=False)
                self.assertIsInstance(result, (list, type(None)))
                np.testing.assert_array_equal(image, before)

    def test_physical_header_keeps_thin_row_and_later_original_text(self):
        image = np.full((110, 5000, 3), 255, dtype=np.uint8)
        image[10, 4:4996] = 0
        cv2.putText(
            image, "Compound 107", (10, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2
        )
        frame = physical_line_frame(image, 4, 400)
        self.assertEqual(len(frame["row_bounds"]), 2)
        original = copy.deepcopy(frame)
        parts, observed = observe_header_lines(image, self.engine, 4, 400, frame=frame)
        self.assertEqual(len(parts), 2)
        self.assertEqual(len(observed["row_readings"]), 2)
        self.assertEqual(observed["row_bounds"], original["row_bounds"])
        self.assertEqual(observed["pixel_sha256"], original["pixel_sha256"])
        self.assertEqual(observed["ink_pixels"], original["ink_pixels"])
        self.assertIn("107", parts[-1]["text"])
        self.assertEqual(observed["status"], "unresolved")

    def test_existing_sdk_inverse_mapping_uses_the_original_coordinate_frame(self):
        for h, w in ((25, 5000), (5000, 25)):
            with self.subTest(height=h, width=w):
                source = np.full((h, w, 3), 255, dtype=np.uint8)
                resized, rh, rw = self.engine.preprocess(source)
                self.assertGreater(min(resized.shape[:2]), 0)
                original = np.array(
                    [[[1, 1], [w - 1, 1], [w - 1, h - 1], [1, h - 1]]], dtype=np.float32
                )
                detected = original / np.array([rw, rh], dtype=np.float32)
                projected = self.engine._get_origin_points(
                    detected, {"preprocess": {"ratio_h": rh, "ratio_w": rw}}, h, w
                )
                np.testing.assert_allclose(projected, original, atol=0.001)
                outer = self.engine._get_origin_points(
                    [
                        [
                            [0, 0],
                            [resized.shape[1], 0],
                            [resized.shape[1], resized.shape[0]],
                            [0, resized.shape[0]],
                        ]
                    ],
                    {"preprocess": {"ratio_h": rh, "ratio_w": rw}},
                    h,
                    w,
                )
                self.assertEqual(float(outer[..., 0].max()), w)
                self.assertEqual(float(outer[..., 1].max()), h)

    def test_valid_sdk_pixels_outputs_scores_and_boxes_are_unchanged(self):
        from rapidocr_onnxruntime import RapidOCR

        image = np.full((55, 300, 3), 255, dtype=np.uint8)
        cv2.putText(
            image, "Compound 107", (12, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2
        )
        for detected in (False, True):
            with self.subTest(detected=detected):
                observed, _ = self.engine(image, use_det=detected, use_cls=False)
                vanilla = RapidOCR.preprocess.__get__(self.engine)
                with patch.object(self.engine, "preprocess", vanilla):
                    original, _ = self.engine(image, use_det=detected, use_cls=False)
                self.assertEqual(observed, original)
                self.assertTrue(observed)
                self.assertIn("107", str(observed))

    def test_unrelated_sdk_errors_are_not_suppressed_or_retried(self):
        with (
            patch.object(
                self.engine,
                "text_rec",
                side_effect=RuntimeError("controlled SDK error"),
            ) as reader,
            self.assertRaisesRegex(RuntimeError, "controlled SDK error"),
        ):
            self.engine(
                np.zeros((25, 5000, 3), dtype=np.uint8),
                use_det=False,
                use_cls=False,
            )
        reader.assert_called_once()

    def test_page_workers_and_diagnostic_excerpt_share_the_same_adapter(self):
        from patent_sar_extractor.core import page_ocr_cache, review_excerpt

        sentinel = object()
        with (
            patch.object(page_ocr_cache, "_paddlex_ocr_url", return_value=""),
            patch(
                "patent_sar_extractor.core.rapidocr_adapter.create_rapidocr",
                return_value=sentinel,
            ) as factory,
        ):
            self.assertEqual(page_ocr_cache._build_ocr_engine(), ("rapidocr", sentinel))
            factory.assert_called_once_with(
                intra_op_num_threads=2, inter_op_num_threads=1
            )
            factory.reset_mock()
            self.assertIs(review_excerpt._load_ocr_engine(), sentinel)
            factory.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
