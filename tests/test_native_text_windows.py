"""Complete native text windows; no OCR, metric tolerance or source trimming."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_text_capture import capture_text_page
from patent_sar_extractor.core.activity_text_sources import (
    original_text_pages_errors,
    text_page_qualified,
)
from patent_sar_extractor.core.source_geometry import source_layout
from patent_sar_extractor.core.source_observations import MAXIMUM_TOKENS
from patent_sar_extractor.core.source_page_lines import native_page_lines

PARAGRAPH = "Binding assay\nCells were seeded and reagent was added.\nResults follow."


class NativeTextWindowTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch(
                "patent_sar_extractor.core.activity_text_capture.get_ocr_engine",
                side_effect=AssertionError(
                    "Native original controls must not start OCR"
                ),
            )
        )

    def test_overlapping_original_lines_share_one_complete_window_without_ocr(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 60), PARAGRAPH, fontsize=10)
            raw = page.get_text("text")
            proof = capture_text_page(page, raw)
            self.assertEqual(len(proof["lines"]), 1)
            self.assertEqual(proof["nomination_text"], raw)
            self.assertTrue(text_page_qualified(proof, raw))
            coverage = {"text_pages": {"1": raw}, "text_sources": {"1": proof}}
            self.assertEqual(original_text_pages_errors(coverage, document), [])
            page.insert_text((40, 130), "Another original statement", fontsize=10)
            self.assertTrue(original_text_pages_errors(coverage, document))

    def test_overpainted_paragraph_is_not_qualified_by_a_complete_window(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 60), PARAGRAPH, fontsize=10)
            page.draw_rect(fitz.Rect(35, 45, 300, 100), color=None, fill=(1, 1, 1))
            raw = page.get_text("text")
            self.assertFalse(text_page_qualified(capture_text_page(page, raw), raw))

    def test_unowned_text_inside_a_combined_rectangle_stays_a_source_conflict(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 60), PARAGRAPH, fontsize=10)
            page.insert_text((70, 79), "Rival", fontsize=8)
            raw = page.get_text("text")
            proof = capture_text_page(page, raw)
            self.assertEqual(proof["nomination_text"], raw)
            self.assertFalse(text_page_qualified(proof, raw))

    def test_rotation_does_not_reorder_native_words(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 60), PARAGRAPH, fontsize=10)
            page.set_rotation(90)
            windows = native_page_lines(source_layout(page))
            self.assertEqual(
                " ".join(window["text"] for window in windows).split(),
                page.get_text("text").split(),
            )

    def test_different_original_blocks_do_not_merge_by_overlap(self):
        tokens = [
            {"text": "first", "line": [0, 0], "bbox": [0, 0, 40, 12], "x": 20, "y": 6},
            {
                "text": "second",
                "line": [1, 0],
                "bbox": [0, 11, 40, 23],
                "x": 20,
                "y": 17,
            },
        ]
        self.assertEqual(len(native_page_lines(SimpleNamespace(native=tokens))), 2)

    def test_over_budget_coalescence_keeps_every_original_line_and_word(self):
        tokens = []
        for index in range(MAXIMUM_TOKENS + 1):
            row, column = divmod(index, 100)
            left, top = 10 * column, 9 * row
            tokens.append(
                {
                    "text": f"w{index}",
                    "line": [0, row],
                    "bbox": [left, top, left + 8, top + 10],
                    "x": left + 4,
                    "y": top + 5,
                }
            )
        windows = native_page_lines(SimpleNamespace(native=tokens))
        self.assertEqual(len(windows), 6)
        self.assertEqual(
            " ".join(window["text"] for window in windows).split(),
            [token["text"] for token in tokens],
        )


if __name__ == "__main__":
    unittest.main()
