"""Physical line coverage, not guessed compound suffixes or OCR voting."""

import copy
import unittest
from unittest.mock import Mock

import numpy as np

from patent_sar_extractor.core.cell_ocr_lines import resolve_overlapping_lines
from patent_sar_extractor.core.cell_ocr_observation import observe_cell
from patent_sar_extractor.core.numbered_structure_pairs import _confirmed_observations
from patent_sar_extractor.core.table_cells import _normalize


def resolved(image, parts, engine, border):
    return resolve_overlapping_lines(image, parts, engine, border, complete_lines=True)


def line(text, left=8, right=180, top=8, bottom=48):
    return {
        "text": text,
        "confidence": 0.99,
        "bbox": [[left, top], [right, top], [right, bottom], [left, bottom]],
        "coordinate_space": "cell_ink_crop_pixels",
    }


def pixels(second_line=False):
    image = np.full((100 if second_line else 56, 340, 3), 255, dtype=np.uint8)
    for left in range(12, 165, 18):
        image[12:44, left : left + 8] = 0
    image[16:44, 210:220] = 0  # Disconnected final character outside the detector.
    if second_line:
        image[76:92, 12:180] = 0
    return image


class CellLineCoverageTests(unittest.TestCase):
    def test_missing_terminal_ink_is_read_from_the_complete_owned_line(self):
        engine = Mock(return_value=([["Compound 137", 0.98]], 0))
        parts = resolved(pixels(), [line("Compound")], engine, 8)
        self.assertEqual(parts[0]["text"], "Compound 137")
        self.assertEqual(parts[0]["method"], "complete_line_recognition")
        self.assertEqual(engine.call_count, 1)
        self.assertFalse(engine.call_args.kwargs["use_det"])
        crop = engine.call_args.args[0]
        self.assertTrue(np.any(crop[:, -20:, :] == 0))

    def test_complete_detector_coverage_does_not_start_another_read(self):
        engine = Mock()
        original = [line("Compound 137", right=230)]
        self.assertEqual(resolved(pixels(), original, engine, 8), original)
        engine.assert_not_called()

    def test_other_physical_line_cannot_be_squeezed_into_the_caption(self):
        engine = Mock(return_value=([["Compound 137", 0.98]], 0))
        parts = resolved(
            pixels(True),
            [line("Compound"), line("eluting isomer", top=72, bottom=96)],
            engine,
            8,
        )
        self.assertEqual([p["text"] for p in parts], ["Compound 137", "eluting isomer"])
        self.assertLess(engine.call_args.args[0].shape[0], 60)
        self.assertEqual(engine.call_count, 1)

    def test_valid_detected_identity_conflict_stays_unresolved(self):
        detected = [line("Compound 138")]
        engine = Mock(
            side_effect=[
                ([(p["bbox"], p["text"], p["confidence"]) for p in detected], 0),
                ([["Compound 137", 0.99]], 0),
            ]
        )
        observed = observe_cell(pixels(), "label", 400, engine, _normalize)
        self.assertEqual(observed.value, "")
        self.assertEqual(observed.detection_parts[0]["text"], "Compound 138")
        self.assertEqual(observed.raw_text, "Compound 137")

    def test_invalid_or_multiple_line_reread_is_not_admitted(self):
        for returned in ([], [["Compound 137", 0.98], ["Compound 138", 0.99]]):
            with self.subTest(returned=returned):
                engine = Mock(return_value=(returned, 0))
                self.assertIsNone(resolved(pixels(), [line("Compound")], engine, 8))
                self.assertEqual(engine.call_count, 1)

    def test_tall_nontext_envelope_is_not_reinterpreted_as_one_line(self):
        image = np.zeros((180, 340, 3), dtype=np.uint8)
        engine = Mock()
        original = [line("Compound", bottom=175)]
        self.assertEqual(resolved(image, original, engine, 8), original)
        engine.assert_not_called()

    def test_unrecognised_original_fragment_cannot_be_silently_replaced(self):
        engine = Mock(
            side_effect=[
                (
                    ([[[8, 8], [180, 8], [180, 48], [8, 48]], "Compound 137.2", 0.99],),
                    0,
                ),
                ([["Compound 137", 0.99]], 0),
            ]
        )
        observed = observe_cell(pixels(), "label", 400, engine, _normalize)
        self.assertEqual(observed.value, "")
        self.assertEqual(observed.detection_parts[0]["text"], "Compound 137.2")

    def test_serialized_replay_preserves_valid_detector_conflicts(self):
        for original in ("Compound 138", "Compound 137.2", "Intermediate 137"):
            with self.subTest(original=original):
                packet = {
                    "method": "cell_ocr_400dpi",
                    "text": "137",
                    "confidence": 0.99,
                    "parts": [
                        {**line("Compound 137"), "method": "complete_line_recognition"}
                    ],
                    "detection_parts": [line(original)],
                }
                self.assertFalse(
                    _confirmed_observations(
                        "137",
                        [{"method": "page_ocr_cell", "text": "Compound 137"}, packet],
                    )
                )

    def test_serialized_complete_line_requires_its_original_detection_packet(self):
        valid = {
            "method": "cell_ocr_400dpi",
            "text": "137",
            "confidence": 0.99,
            "parts": [{**line("Compound 137"), "method": "complete_line_recognition"}],
            "detection_parts": [line("Compound")],
        }
        page = {"method": "page_ocr_cell", "text": "Compound 137"}
        self.assertTrue(_confirmed_observations("137", [page, valid]))
        for bad in (
            None,
            [],
            [{}],
            [line("Compound", left=-1)],
            [line("Compound", right=float("nan"))],
        ):
            packet = copy.deepcopy(valid)
            packet["detection_parts"] = bad
            with self.subTest(bad=bad):
                self.assertFalse(_confirmed_observations("137", [page, packet]))

    def test_bool_line_confidence_does_not_prove_an_identity(self):
        engine = Mock(
            side_effect=[
                (([[[8, 8], [180, 8], [180, 48], [8, 48]], "Compound", 0.99],), 0),
                ([["Compound 137", True]], 0),
            ]
        )
        observed = observe_cell(pixels(), "label", 400, engine, _normalize)
        self.assertEqual(observed.value, "")
        self.assertEqual(observed.confidence, 0)

    def test_noncaption_cells_do_not_use_whole_caption_refinement(self):
        original = [line("IC50")]
        engine = Mock()
        self.assertEqual(
            resolve_overlapping_lines(pixels(), original, engine, 8), original
        )
        engine.assert_not_called()

    def test_nonoverlapping_split_caption_still_retains_a_valid_conflict(self):
        packet = {
            "method": "cell_ocr_400dpi",
            "text": "137",
            "confidence": 0.99,
            "parts": [{**line("Compound 137"), "method": "complete_line_recognition"}],
            "detection_parts": [
                line("Compound", right=140),
                line("138", left=150, right=200),
            ],
        }
        self.assertFalse(
            _confirmed_observations(
                "137", [{"method": "page_ocr_cell", "text": "Compound 137"}, packet]
            )
        )

    def test_physical_image_budget_refuses_extra_recognition(self):
        image = np.ones((2000, 4001, 3), dtype=np.uint8)
        engine = Mock()
        self.assertIsNone(resolved(image, [line("Compound")], engine, 8))
        engine.assert_not_called()
