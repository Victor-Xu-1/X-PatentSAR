import unittest
from unittest.mock import Mock, patch

import fitz

from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema


class HeaderObservationTests(unittest.TestCase):
    def observe(self, rows):
        page = Mock(rect=fitz.Rect(0, 0, 500, 600))
        page.get_text.return_value = []
        original = grid_schema(
            context_from_text("Tabie 7. Binding assay"), [["No.", "Noise", "IC50 (nM)"]]
        )
        region = {"xs": [40, 80, 150, 220], "ys": [100, 140, 170]}
        with (
            patch(
                "patent_sar_extractor.core.activity_header_observation.ocr_tokens_with_positions",
                return_value=[],
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation.table_matrix",
                side_effect=rows,
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation._prefix",
                return_value="Table 7. Binding assay",
            ),
        ):
            return original, refine_scanned_header(page, region, original)

    def test_caption_consensus_survives_unresolved_individual_header(self):
        original, result = self.observe(
            [
                [["No.", "Dmax (%)", "IC50 (nM)"]],
                [["No.", "Dniax (%)", "IC50 (nM)"]],
            ]
        )
        self.assertEqual(result.context.table_id, "Table 7")
        self.assertEqual(result.raw_headers[1], original.raw_headers[1])
        self.assertEqual(result.header_resolution["status"], "unresolved")

    def test_complete_header_agreement_is_recorded_without_value_repair(self):
        _, result = self.observe([[["No.", "Dmax (%)", "IC50 (nM)"]]] * 2)
        self.assertEqual(result.raw_headers[1], "Dmax (%)")
        self.assertEqual(
            result.header_resolution["status"], "observed_header_consensus"
        )

    def test_native_header_never_invokes_ocr(self):
        page = Mock()
        page.get_text.return_value = [("native",)]
        original = grid_schema(
            context_from_text("Table 7. Binding"), [["No.", "IC50 (nM)"]]
        )
        with patch(
            "patent_sar_extractor.core.activity_header_observation.ocr_tokens_with_positions"
        ) as ocr:
            self.assertIs(refine_scanned_header(page, {}, original), original)
        ocr.assert_not_called()
