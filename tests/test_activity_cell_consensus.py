"""Missing markers and malformed page OCR never become invented measurements."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_grid_cells import read_activity_cell
from patent_sar_extractor.core.table_cells import CellReading, _normalize
from patent_sar_extractor.core.table_geometry import ocr_tokens_with_positions


class ActivityCellConsensusTests(unittest.TestCase):
    def test_original_upright_grid_does_not_rotate_isolated_digits(self):
        with fitz.open() as document:
            page = document.new_page(width=200, height=200)
            with patch(
                "patent_sar_extractor.core.table_geometry.get_ocr_engine"
            ) as engine:
                backend = engine.return_value = (
                    "rapidocr",
                    unittest.mock.Mock(return_value=([], None)),
                )
                ocr_tokens_with_positions(page, allow_tesseract=False)
                self.assertFalse(backend[1].call_args.kwargs["use_cls"])

    def test_independent_cell_read_proves_value_despite_oversized_detector_box(self):
        bounds = (0, 0, 100, 20)
        tokens = [{"text": "4.01", "x": 50, "y": 10, "bbox": [-2, 0, 102, 20]}]
        sources = [
            {"method": "page_ocr_cell", "text": "4.01"},
            {"method": "cell_ocr_400dpi", "text": "4.01", "confidence": 0.99},
        ]
        with patch(
            "patent_sar_extractor.core.activity_grid_cells.read_cell",
            return_value=CellReading("4.01", bounds, sources, False),
        ):
            self.assertFalse(
                read_activity_cell(
                    None, tokens, bounds, identifier=False, native=False
                )[2]
            )
        self.assertTrue(
            read_activity_cell(None, tokens, bounds, identifier=False, native=True)[2]
        )

    def test_scalar_observation_keeps_missing_markers_comparators_units_and_sign(self):
        for value in (
            "NA",
            "N/A",
            "ND",
            "NT",
            "-4.01",
            "> 100",
            "0.2 nM",
            "1.2e-3",
            "3.2 ± 0.1",
        ):
            with self.subTest(value=value):
                self.assertEqual(_normalize(value, "number"), value)
        self.assertEqual(_normalize("NA", "id"), "")
        self.assertEqual(_normalize("1 0", "number"), "")

    def test_two_agreeing_cell_reads_recover_only_invalid_page_text(self):
        bounds = (0, 0, 100, 20)
        tokens = [{"text": "10't", "x": 50, "y": 10}]
        observations = [
            {"method": "page_ocr_cell", "text": "10't"},
            {"method": "cell_ocr_400dpi", "text": "4.01", "confidence": 0.99},
            {"method": "cell_ocr_600dpi", "text": "4.01", "confidence": 0.99},
        ]
        with patch(
            "patent_sar_extractor.core.activity_grid_cells.read_cell",
            return_value=CellReading("4.01", bounds, observations, False),
        ):
            value, sources, review = read_activity_cell(
                None, tokens, bounds, identifier=False, native=False
            )
        self.assertEqual(value, "4.01")
        self.assertFalse(review)
        self.assertEqual(sources[0]["text"], "10't")

    def test_conflicting_valid_numbers_or_lost_comparator_still_require_review(self):
        bounds = (0, 0, 100, 20)
        for raw, refined in (("4.02", "4.01"), (">4.01", "4.01"), ("0.2 nM", "0.2")):
            tokens = [{"text": raw, "x": 50, "y": 10}]
            with patch(
                "patent_sar_extractor.core.activity_grid_cells.read_cell",
                return_value=CellReading(refined, bounds, [], False),
            ):
                value, _, review = read_activity_cell(
                    None, tokens, bounds, identifier=False, native=False
                )
            self.assertEqual(value, raw)
            self.assertTrue(review)


if __name__ == "__main__":
    unittest.main()
