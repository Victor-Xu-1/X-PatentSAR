"""Actual text-role/parser controls without renderer or model dependencies."""

import unittest

from patent_sar_extractor.core.activity_observations import has_usable_values
from patent_sar_extractor.core.activity_text_rows import _find_header, parse_segment


class ActivityTextRoleTests(unittest.TestCase):
    def test_explicit_header_precedes_an_alphanumeric_target_prefix(self):
        header, first = _find_header(["Target7 cells I-# DC50 (nM)", "I-3 B"])
        self.assertEqual(header, "I-# DC50 (nM)")
        self.assertEqual(first, 1)

    def test_alphanumeric_ids_remain_valid_in_the_actual_identifier_column(self):
        rows = parse_segment("Table 7. Binding", "No. | IC50 (nM)\nIRF5 | 0.2")
        self.assertEqual([row.cpd for row in rows], ["Compound IRF5"])
        self.assertEqual(rows[0].activity_values, {"IC50 (nM)": "0.2"})

    def test_a_split_metric_header_is_not_an_identifier_row(self):
        header, first = _find_header(["No.", "EC50 (nM)", "C17 0.3"])
        self.assertEqual(header, "No. EC50 (nM)")
        self.assertEqual(first, 2)

    def test_original_grade_and_missingness_use_the_matching_literal_legend(self):
        rows = parse_segment(
            "Table 7. Binding assay",
            "letter codes for IC50 include: A (<1 nM) B (1-10 nM) G (not tested).\n"
            "Table 7. Binding assay\nNo. | IC50 (nM)\n31 | A\n32 | G",
        )
        self.assertEqual(
            [list(r.activity_values.values()) for r in rows], [["A"], ["G"]]
        )
        self.assertEqual(rows[0].activity_sources[0]["legend"]["A"], "<1 nM")
        self.assertTrue(has_usable_values(rows[0]))
        self.assertFalse(has_usable_values(rows[1]))

    def test_a_different_endpoint_cannot_supply_the_grade_meaning(self):
        rows = parse_segment(
            "Table 7. Degradation assay",
            "letter codes for IC50 include: A (<1 nM) B (1-10 nM)\n"
            "No. | DC50 (nM)\n31 | A",
        )
        self.assertEqual(rows[0].activity_values, {"DC50 (nM)": "A"})
        self.assertTrue(rows[0].needs_review)
        self.assertTrue(rows[0].activity_sources[0]["legend_issues"])


if __name__ == "__main__":
    unittest.main()
