"""Shared cell admission must preserve every original valid contradiction."""

import json
import unittest
from unittest.mock import Mock, patch

import numpy as np

from patent_sar_extractor.core.table_cells import _ocr_cell, read_cell


def detected(text, confidence, top=0):
    return [[[0, top], [300, top], [300, top + 30], [0, top + 30]], text, confidence]


class CellObservationProvenanceTests(unittest.TestCase):
    def observation(self, parts, kind="label"):
        engine = Mock(return_value=(parts, 0))
        with (
            patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                return_value=("rapidocr", engine),
            ),
            patch(
                "patent_sar_extractor.core.table_cells.cell_image",
                return_value=np.zeros((120, 320, 3), dtype=np.uint8),
            ),
        ):
            result = _ocr_cell(None, (0, 0, 100, 30), kind, 400)
        return result, engine

    def test_literal_annotation_confidence_does_not_erase_proved_identifier(self):
        result, _ = self.observation(
            [
                detected("Compound 73", 0.99),
                detected("*first eluting isomer", 0.61, 60),
            ]
        )
        self.assertEqual(result.value, "73")
        self.assertEqual(result.confidence, 0.99)
        self.assertEqual(result.raw_text, "Compound 73 *first eluting isomer")
        self.assertEqual(result.parts[1]["confidence"], 0.61)

    def test_unknown_annotation_is_not_silently_dropped(self):
        result, _ = self.observation(
            [
                detected("Compound 73", 0.99),
                detected("prepared from Compound 74", 0.61, 60),
            ]
        )
        self.assertEqual(result.value, "")
        self.assertIn("Compound 74", result.raw_text)

    def test_identifier_confidence_cannot_be_borrowed_from_its_annotation(self):
        result, _ = self.observation(
            [
                detected("Compound 73", 0.61),
                detected("*first eluting isomer", 0.99, 60),
            ]
        )
        self.assertEqual(result.value, "")
        self.assertEqual(result.confidence, 0.61)

    def test_split_identifier_requires_confidence_of_every_identity_fragment(self):
        result, _ = self.observation(
            [
                detected("Compound", 0.99),
                detected("73 *second eluting isomer", 0.60, 60),
            ]
        )
        self.assertEqual(result.value, "")

    def test_two_valid_high_resolution_reads_do_not_overrule_valid_page_read(self):
        for kind, printed, fresh in (
            ("id", "73", "74"),
            ("label", "Compound 73", "Compound 74"),
            ("number", "4.1", "4.7"),
        ):
            with self.subTest(kind=kind):
                parts = [detected(fresh, 0.99)] if kind == "label" else [[fresh, 0.99]]
                engine = Mock(return_value=(parts, 0))
                with (
                    patch(
                        "patent_sar_extractor.core.table_cells.get_ocr_engine",
                        return_value=("rapidocr", engine),
                    ),
                    patch(
                        "patent_sar_extractor.core.table_cells.cell_image",
                        return_value=np.zeros((120, 320, 3), dtype=np.uint8),
                    ),
                ):
                    result = read_cell(
                        None,
                        (0, 0, 100, 30),
                        [{"text": printed, "x": 20, "y": 10}],
                        kind,
                        False,
                    )
                self.assertTrue(result.needs_review)
                self.assertEqual(result.observations[0]["text"], printed)
                self.assertEqual(result.observations[1]["raw_text"], fresh)
                self.assertEqual(result.observations[2]["raw_text"], fresh)

    def test_unread_normalization_keeps_raw_text_and_parts(self):
        result, _ = self.observation([detected("Compoumd 73", 0.99)])
        self.assertEqual(result.value, "")
        self.assertEqual(result.raw_text, "Compoumd 73")
        self.assertEqual(len(result.parts), 1)

    def test_single_line_caption_is_detected_not_squeezed_as_scalar(self):
        engine = Mock(return_value=([detected("Compound 73", 0.99)], 0))
        image = np.zeros((35, 320, 3), dtype=np.uint8)
        with (
            patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                return_value=("rapidocr", engine),
            ),
            patch(
                "patent_sar_extractor.core.table_cells.cell_image", return_value=image
            ),
        ):
            _ocr_cell(None, (0, 0, 100, 10), "label", 400)
        self.assertTrue(engine.call_args.kwargs["use_det"])

    def test_overlapping_detector_digits_are_recognized_from_one_physical_line(self):
        overlapping = [
            [[[0, 0], [220, 0], [220, 40], [0, 40]], "Compound 9", 0.99],
            [[[195, 0], [300, 0], [300, 40], [195, 40]], "95", 0.99],
        ]
        engine = Mock(side_effect=[(overlapping, 0), ([["Compound 95", 0.99]], 0)])
        with (
            patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                return_value=("rapidocr", engine),
            ),
            patch(
                "patent_sar_extractor.core.table_cells.cell_image",
                return_value=np.zeros((120, 320, 3), dtype=np.uint8),
            ),
        ):
            result = _ocr_cell(None, (0, 0, 100, 30), "label", 400)
        self.assertEqual(result.value, "95")
        self.assertEqual(result.raw_text, "Compound 95")
        self.assertEqual(result.detection_parts[1]["text"], "95")
        self.assertEqual(result.parts[0]["method"], "overlapping_line_recognition")
        self.assertEqual(engine.call_count, 2)
        self.assertFalse(engine.call_args.kwargs["use_det"])
        json.dumps(result.evidence(400, (0, 0, 100, 30)), allow_nan=False)

    def test_cross_line_detector_fragment_is_unowned_not_merged(self):
        parts = [
            detected("Compound 73", 0.99),
            detected("eluting isomer", 0.99, 80),
            [[[280, 10], [300, 10], [300, 110], [280, 110]], "first", 0.99],
        ]
        result, engine = self.observation(parts)
        self.assertEqual(result.value, "")
        self.assertTrue(result.raw_text)
        self.assertEqual(engine.call_count, 1)

    def test_excess_detected_lines_stop_without_unbounded_refinement(self):
        result, engine = self.observation(
            [detected("Compound 73", 0.99, i * 60) for i in range(9)]
        )
        self.assertEqual(result.value, "")
        self.assertEqual(len(result.detection_parts), 9)
        self.assertEqual(engine.call_count, 1)
