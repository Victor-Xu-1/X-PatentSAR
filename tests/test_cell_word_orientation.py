"""Original-mask geometry, transform replay and same-engine literal readings."""

import copy
import hashlib
import unittest

import cv2
import numpy as np

from patent_sar_extractor.core.cell_ocr_observation import observe_cell
from patent_sar_extractor.core.cell_text_proof import valid_text_components
from patent_sar_extractor.core.cell_word_orientation import (
    rectified_word,
    valid_word_frame,
    word_frame,
)
from patent_sar_extractor.core.page_ocr_cache import get_ocr_engine
from patent_sar_extractor.core.table_cells import cell_image
from tests.test_plot_reference_layout import plot_document


class OriginalWordOrientationTests(unittest.TestCase):
    def test_complete_original_masks_replay_at_both_resolutions_and_different_angles(
        self,
    ):
        for angle in (0, 45, 90, -45):
            with self.subTest(angle=angle), plot_document(angle) as document:
                for dpi in (400, 600):
                    image = cell_image(document[0], [90, 260, 320, 335], dpi)
                    mask = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) < 180
                    frame = word_frame(mask, dpi)
                    self.assertIsNotNone(frame)
                    self.assertTrue(valid_word_frame(frame, mask, dpi))
                    self.assertEqual(len(frame["word_bounds"]), 4)
                    coverage = np.zeros_like(mask)
                    for box in frame["word_bounds"]:
                        coverage[box[1] : box[3], box[0] : box[2]] = True
                        view = rectified_word(mask, box, frame["angle"], dpi)
                        self.assertEqual(
                            hashlib.sha256(view.tobytes()).digest(),
                            hashlib.sha256(
                                rectified_word(mask, box, frame["angle"], dpi).tobytes()
                            ).digest(),
                        )
                    self.assertFalse(np.any(mask & ~coverage))
                    for mutation in ("omit", "order", "angle", "bool"):
                        changed = copy.deepcopy(frame)
                        if mutation == "omit":
                            changed["word_bounds"].pop()
                        elif mutation == "order":
                            changed["word_bounds"].reverse()
                        elif mutation == "angle":
                            changed["angle"] += 180
                        else:
                            changed["word_bounds"][0][0] = True
                        self.assertFalse(valid_word_frame(changed, mask, dpi))

    def test_real_existing_ocr_reads_every_oriented_word_without_character_repair(self):
        engine = get_ocr_engine()[1]
        for angle in (45, 90):
            with self.subTest(angle=angle), plot_document(angle) as document:
                for dpi in (400, 600):
                    image = cell_image(document[0], [90, 260, 320, 335], dpi)
                    mask = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) < 180
                    frame = word_frame(mask, dpi)
                    texts = []
                    for box in frame["word_bounds"]:
                        view = rectified_word(mask, box, frame["angle"], dpi)
                        observed = observe_cell(
                            view, "header", dpi, engine, lambda text, _: text
                        )
                        reading = observed.evidence(
                            dpi, [0, 0, view.shape[1], view.shape[0]]
                        )
                        self.assertTrue(valid_text_components(reading, dpi), reading)
                        texts.append(observed.raw_text)
                    self.assertEqual(texts, ["0.001", "0.1", "1", "100"])

    def test_empty_or_direction_ambiguous_ink_cannot_choose_a_rotation(self):
        self.assertIsNone(word_frame(np.zeros((100, 300), dtype=np.uint8), 400))
        ambiguous = np.zeros((100, 300), dtype=np.uint8)
        for x in (20, 110, 200):
            ambiguous[20:80, x : x + 12] = 1
        self.assertIsNone(word_frame(ambiguous, 400))
        with self.assertRaises(ValueError):
            word_frame(np.full((100, 300), 255, dtype=np.uint8), 400)
        with self.assertRaises(ValueError):
            word_frame(ambiguous, True)


if __name__ == "__main__":
    unittest.main()
