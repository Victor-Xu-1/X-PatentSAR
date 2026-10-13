"""Header provenance must retain valid source conflicts and literal units."""

import unittest
from unittest.mock import Mock, patch

import fitz

from patent_sar_extractor.core.activity_header_columns import HeaderColumns
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_headers import (
    context_from_text,
    grid_schema,
    infer_value_keys,
)


class HeaderSemanticConflictTests(unittest.TestCase):
    def refine(
        self,
        old,
        fresh,
        *,
        old_caption="Table 7. Binding assay",
        fresh_caption="Table 7. Binding assay",
    ):
        page = Mock(rect=fitz.Rect(0, 0, 500, 600))
        page.get_text.return_value = []
        original = grid_schema(context_from_text(old_caption), [["No.", old]])
        region = {"xs": [40, 90, 220], "ys": [100, 140, 170]}
        with (
            patch(
                "patent_sar_extractor.core.activity_header_observation.ocr_tokens_with_positions",
                return_value=[],
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation.observe_header_columns",
                return_value=HeaderColumns([["No.", fresh]], (), (True, True)),
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation._prefix",
                return_value=fresh_caption,
            ),
        ):
            return refine_scanned_header(page, region, original)

    def test_two_matching_reads_cannot_overrule_a_valid_original_endpoint(self):
        result = self.refine("IC50 (nM)", "EC50 (nM)")
        self.assertEqual(result.raw_headers[1], "IC50 (nM)")
        self.assertEqual(result.header_resolution["status"], "unresolved")

    def test_known_original_unit_cannot_be_replaced_by_two_matching_other_units(self):
        result = self.refine("IC50 (nM)", "IC50 (uM)")
        self.assertEqual(result.raw_headers[1], "IC50 (nM)")
        self.assertEqual(result.header_resolution["status"], "unresolved")

    def test_partial_known_endpoint_is_not_free_to_become_another_endpoint(self):
        result = self.refine("IC50", "EC50 (nM)")
        self.assertEqual(result.raw_headers[1], "IC50")
        self.assertEqual(result.header_resolution["status"], "unresolved")

    def test_valid_printed_table_identity_cannot_be_renamed_by_consensus(self):
        result = self.refine(
            "IC50 (nM)", "IC50 (nM)", fresh_caption="Table 8. Binding assay"
        )
        self.assertEqual(result.context.table_id, "Table 7")
        self.assertEqual(result.header_resolution["status"], "unresolved")

    def test_unknown_original_header_can_still_receive_literal_complete_proof(self):
        result = self.refine("Noise", "Dmax (%)")
        self.assertEqual(result.raw_headers[1], "Dmax (%)")
        self.assertEqual(
            result.header_resolution["status"], "observed_header_consensus"
        )

    def test_concatenated_literal_potency_units_do_not_require_user_matching(self):
        for header, expected in (
            ("NEK7 NanoBiT DC50nM", "NEK7 NanoBiT DC50 (nM)"),
            ("IC50µM", "IC50 (µM)"),
            ("EC50pM", "EC50 (pM)"),
        ):
            with self.subTest(header=header):
                self.assertEqual(infer_value_keys("", header, 1), [expected])
        self.assertIn("unknown", infer_value_keys("", "DC50nm", 1)[0].lower())

    def test_equivalent_literal_unit_spelling_and_layout_is_not_a_conflict(self):
        for old, fresh in (("IC50\nnM", "IC50 (nM)"), ("IC50 (uM)", "IC50 (µM)")):
            with self.subTest(old=old, fresh=fresh):
                result = self.refine(old, fresh)
                self.assertEqual(
                    result.header_resolution["status"], "observed_header_consensus"
                )
