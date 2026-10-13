"""Invalid/ambiguous physical header ownership never becomes fresh admission."""

import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import fitz

from patent_sar_extractor.core.activity_header_columns import HeaderColumns
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema


class HeaderColumnBoundaryTests(unittest.TestCase):
    def page(self):
        page = Mock(rect=fitz.Rect(0, 0, 500, 600))
        page.get_text.return_value = []
        return page

    def schema(self):
        return grid_schema(
            context_from_text("Table 7. Binding assay"), [["No.", "IC50 (nM)"]]
        )

    def test_invalid_bounds_do_not_start_an_engine_and_remain_unresolved(self):
        for region in (
            {"xs": [40, 80, 150], "ys": [100, 600]},
            {"xs": [40, 80, 150], "ys": [100, 90, 170]},
            {"xs": [40, True, 150], "ys": [100, 140, 170]},
            {"xs": [40, float("nan"), 150], "ys": [100, 140, 170]},
            {"xs": list(range(66)), "ys": [100, 140, 170]},
        ):
            with (
                self.subTest(region=region),
                patch(
                    "patent_sar_extractor.core.activity_header_observation.observe_header_columns"
                ) as reader,
            ):
                original = self.schema()
                sink = []
                result = refine_scanned_header(
                    self.page(), region, original, evidence_sink=sink
                )
                self.assertEqual(result.header_resolution["status"], "unresolved")
                self.assertEqual(sink, [result.header_resolution])
                reader.assert_not_called()

    def test_invalid_original_header_row_cannot_index_an_unowned_row(self):
        for row in (True, 99, -1):
            original = replace(self.schema(), first_data_row=row)
            with (
                self.subTest(row=row),
                patch(
                    "patent_sar_extractor.core.activity_header_observation.observe_header_columns"
                ) as reader,
            ):
                result = refine_scanned_header(
                    self.page(), {"xs": [40, 80, 150], "ys": [100, 140]}, original
                )
                self.assertEqual(result.header_resolution["status"], "unresolved")
                reader.assert_not_called()

    def test_cross_boundary_or_low_confidence_header_stays_review_only(self):
        for verified in ((True, False), (False, True)):
            original = self.schema()
            with (
                patch(
                    "patent_sar_extractor.core.activity_header_observation.observe_header_columns",
                    return_value=HeaderColumns([["No.", "IC50 (nM)"]], (), verified),
                ),
                patch(
                    "patent_sar_extractor.core.activity_header_observation.ocr_tokens_with_positions",
                    return_value=[],
                ),
                patch(
                    "patent_sar_extractor.core.activity_header_observation._prefix",
                    return_value="Table 7. Binding assay",
                ),
            ):
                result = refine_scanned_header(
                    self.page(), {"xs": [40, 80, 150], "ys": [100, 140]}, original
                )
            self.assertEqual(result.header_resolution["status"], "unresolved")

    def test_rejected_missing_header_discovery_preserves_observations(self):
        from patent_sar_extractor.core.activity_header_layout import HeaderLayout

        raw = ({"method": "header_layout_400dpi", "matrix": [["No", "IC50 nM"]]},)
        sink = []
        with patch(
            "patent_sar_extractor.core.activity_header_observation.discover_header_layout",
            return_value=HeaderLayout(None, raw),
        ):
            result = refine_scanned_header(
                self.page(),
                {"xs": [40, 80, 150], "ys": [100, 140, 170]},
                None,
                evidence_sink=sink,
            )
        self.assertIsNone(result)
        self.assertEqual(sink[0]["status"], "unresolved")
        self.assertEqual(sink[0]["discovery_observations"], list(raw))
