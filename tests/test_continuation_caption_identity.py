"""Whole caption words cannot disappear when an original table is continued."""

import unittest

import fitz

from patent_sar_extractor.core.activity_continuation_policy import (
    caption_prefix,
    continued_context_prefix,
)
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_headers import context_from_text
from tests.test_activity_parallel_grids import panel


def native_continuation(original, current):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 80), original, fontsize=9)
        panel(page, 40, 100, [["No.", "IC50 (nM)", "Dmax (%)"], ["7", "3", "90"]])
        page = doc.new_page()
        page.insert_text((40, 70), current, fontsize=9)
        panel(page, 40, 90, [["19", "4", "80"]])
        return extract_coordinate_tables(doc, [0])


class ContinuationCaptionIdentityTests(unittest.TestCase):
    def test_ordinary_words_and_measurement_qualifiers_are_not_compacted(self):
        for original, current in (
            ("Assay ABC", "Assay AB C"),
            ("Assay AB C", "Assay ABC"),
            ("Construct AB C", "Construct ABC"),
            ("IC50 (AB C)", "IC50 (ABC)"),
            ("Dose 10 nM", "Dose 10nM"),
            ("Results at 2 h", "Results at 2h"),
            ("Series A-B", "Series AB"),
            ("Series 037B", "Series 37B"),
        ):
            title = "Table 8. " + original
            boundary = "Table 8. " + current + " (continued)"
            context = context_from_text(title)
            with self.subTest(original=original, current=current):
                self.assertFalse(
                    caption_prefix(boundary, "Table 8", title, continued=True)
                )
                self.assertFalse(continued_context_prefix(boundary, context))
                self.assertEqual(context.raw_caption, title)

    def test_explicit_table_marker_and_known_metric_typography_remain_legal(self):
        for original, current in (
            ("Table 8. Assay ABC", "Table8. Assay ABC (continued)"),
            ("Table 8. Assay ABC", "[0042] Table 8. Assay\nABC (continued)"),
            ("Table 8. IC50 (nM) activity", "Table 8. IC50(nM) activity (continued)"),
            ("Table 8. Dmax (%) activity", "Table 8. Dmax(%) activity (continued)"),
        ):
            with self.subTest(original=original, current=current):
                self.assertTrue(
                    caption_prefix(current, "Table 8", original, continued=True)
                )
                self.assertTrue(
                    continued_context_prefix(current, context_from_text(original))
                )

    def test_new_ids_missing_titles_and_unknown_conditions_still_refuse(self):
        title = "Table 8. Assay ABC"
        context = context_from_text(title)
        for boundary in (
            "Table 9. Assay ABC (continued)",
            "Table 8. Assay XYZ (continued)",
            "Table 8. Assay ABC",
            "Table 8. Assay ABC (continued)\nTarget: JAK",
        ):
            with self.subTest(boundary=boundary):
                self.assertFalse(continued_context_prefix(boundary, context))

    def test_native_word_boundary_change_cannot_borrow_prior_rows_or_keys(self):
        result = native_continuation(
            "Table 71. Assay ABC", "Table 71. Assay AB C (continued)"
        )
        self.assertEqual([row.cpd for row in result.rows], ["Compound 7"])
        self.assertTrue(
            any(
                region["page_no"] == 2 and region["status"] == "unresolved"
                for region in result.coverage
            )
        )

    def test_native_legal_metric_spacing_preserves_all_source_rows(self):
        result = native_continuation(
            "Table 71. IC50 (nM) activity", "Table 71. IC50(nM) activity (continued)"
        )
        self.assertEqual(
            [row.cpd for row in result.rows], ["Compound 7", "Compound 19"]
        )
        self.assertTrue(all(not row.needs_review for row in result.rows))
        self.assertTrue(all(region["status"] == "parsed" for region in result.coverage))


if __name__ == "__main__":
    unittest.main()
