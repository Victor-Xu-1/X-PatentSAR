"""Proved empty original native cells keep the gap without loading OCR."""

import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.table_cells import read_cell


class EmptyCellReadingTests(unittest.TestCase):
    def test_closed_empty_original_skips_ocr_but_keeps_missing_identifier_review(self):
        with fitz.open() as document:
            page = document.new_page(width=200, height=120)
            page.draw_rect(fitz.Rect(20, 20, 140, 70))
            tokens = SourceTokens([], source_layout(page))
            with patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                side_effect=AssertionError("A proved blank cannot load OCR"),
            ) as reader:
                result = read_cell(page, (20, 20, 140, 70), tokens, "id", False)
            self.assertEqual(result.value, "")
            self.assertTrue(result.needs_review)
            self.assertEqual(result.observations[0]["source_observation"]["text"], "")
            reader.assert_not_called()

    def test_unknown_ink_or_missing_edges_cannot_be_called_a_proved_blank(self):
        for mode in ("unknown_ink", "open_edge"):
            with self.subTest(mode=mode), fitz.open() as document:
                page = document.new_page(width=200, height=120)
                page.draw_line((20, 20), (140, 20))
                page.draw_line((20, 70), (140, 70))
                page.draw_line((20, 20), (20, 70))
                if mode == "unknown_ink":
                    page.draw_line((140, 20), (140, 70))
                    page.draw_line((40, 35), (80, 50))
                tokens = SourceTokens([], source_layout(page))
                with (
                    patch(
                        "patent_sar_extractor.core.table_cells._ocr_cell",
                        side_effect=RuntimeError(
                            "controlled physical cell needs reading"
                        ),
                    ),
                    self.assertRaisesRegex(RuntimeError, "physical cell needs reading"),
                ):
                    read_cell(page, (20, 20, 140, 70), tokens, "id", False)


if __name__ == "__main__":
    unittest.main()
