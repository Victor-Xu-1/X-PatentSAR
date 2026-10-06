"""Synthetic controls for evidence-only activity parsing, not scientific QA."""

from __future__ import annotations

import unittest

from patent_sar_extractor.core.activity_headers import infer_value_keys
from patent_sar_extractor.core.activity_models import ActivityRow
from patent_sar_extractor.core.activity_observations import (
    DEFAULT_OCR_FIXES,
    apply_ocr_fixes,
    merge_rows,
)
from patent_sar_extractor.core.activity_text import extract_text_tables, parse_segment


class ActivityEvidenceTests(unittest.TestCase):
    def test_htrf_table3_does_not_fabricate_nrf2_cell_lines(self):
        self.assertEqual(
            infer_value_keys("表3 HTRF assay", "Compound No. EGFR IC50 (nM)", 1),
            ["EGFR IC50 (nM)"],
        )

    def test_header_order_and_context_not_metric_dictionary_order(self):
        self.assertEqual(
            infer_value_keys(
                "Table 91 kinase assay",
                "Compound No. BRAF Dmax (%) EGFR DC50 (uM) BRAF IC50 (nM)",
                3,
            ),
            ["BRAF Dmax (%)", "EGFR DC50 (uM)", "BRAF IC50 (nM)"],
        )

    def test_absent_unit_and_field_are_explicit_unknown(self):
        self.assertEqual(
            infer_value_keys("Table 2 assay", "No. EGFR IC50", 2),
            ["EGFR IC50 (unit unknown)", "Unknown activity field 2 (unit unknown)"],
        )

    def test_novel_bare_no_table_preserves_suffixes_without_fixed_endpoints(self):
        rows = extract_text_tables(
            [0], {"0": "Table 77 HTRF assay\nNo. EGFR IC50 (uM)\n44A 0.7\n44B N/A"}
        ).rows
        self.assertEqual([r.cpd for r in rows], ["Compound 44A", "Compound 44B"])
        self.assertEqual(rows[0].activity_values, {"EGFR IC50 (uM)": "0.7"})
        self.assertEqual(rows[1].activity_values, {"EGFR IC50 (uM)": "N/A"})

    def test_legitimate42_and17_remain42_and17_in_chinese_table3(self):
        rows = extract_text_tables(
            [0],
            {
                "0": (
                    "表3 VAV1 degradation\n化合物编号 DC50(nM) Dmax(%)\n"
                    "化合物42 A 93\n43 17 95\n化合物4-2 B 86"
                )
            },
        ).rows
        self.assertEqual(
            [r.cpd for r in rows], ["Compound 42", "Compound 43", "Compound 4-2"]
        )
        self.assertIn("17", rows[1].activity_values.values())
        self.assertNotIn("1.7", rows[1].activity_values.values())
        self.assertFalse(
            any(
                "Whole blood" in key or "Jurkat" in key
                for r in rows
                for key in r.activity_values
            )
        )

    def test_xenograft_table_number_cannot_supply_cell_line(self):
        header = "Compound No. Dose (mg/kg) Tumor volume (mm3) TGI (%) p value"
        for number in (9, 11, 71):
            with self.subTest(number=number):
                caption = f"表{number} xenograft assay"
                rows = parse_segment(
                    caption,
                    f"[[PAGE 8]]\n{caption}\n{header}\nCompound 42 3 100 65 0.01",
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    list(rows[0].activity_values.values()), ["3", "100", "65", "0.01"]
                )
                self.assertFalse(
                    any(
                        "KYSE" in key or "HCC95" in key
                        for key in rows[0].activity_values
                    )
                )

    def test_missing_cell_does_not_shift_following_metric(self):
        rows = parse_segment(
            "Table 18 EGFR assay",
            "[[PAGE 2]]\nTable 18 EGFR assay\nCompound No.\tIC50 (nM)\tDmax (%)\n"
            "Compound 7\t\t85\nCompound 8\tN/A\t90",
        )
        self.assertEqual(rows[0].activity_values.get("IC50 (nM)"), "")
        self.assertEqual(rows[0].activity_values.get("Dmax (%)"), "85")
        self.assertTrue(rows[0].needs_review)
        self.assertEqual(rows[1].activity_values.get("IC50 (nM)"), "N/A")

    def test_missing_unpositioned_value_is_withheld_not_assigned(self):
        rows = parse_segment(
            "Table 19 assay",
            "[[PAGE 2]]\nTable 19 assay\nCompound No. IC50 (nM) Dmax (%)\nCompound 9 85",
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].needs_review)
        self.assertNotIn("85", rows[0].activity_values.values())
        self.assertIn("85", str(rows[0].activity_sources))

    def test_repeated_measurements_are_not_confidence_selected_or_erased(self):
        rows = merge_rows(
            [
                ActivityRow(
                    cpd="Compound 42",
                    activity_values={"IC50 (nM)": value},
                    page_no=page,
                    table_id="Table 9",
                    confidence=confidence,
                    activity_sources=[{"page_no": page, "table_id": "Table 9"}],
                )
                for value, page, confidence in (
                    ("17", 2, 0.8),
                    ("29", 3, 0.95),
                    ("17", 4, 0.9),
                )
            ]
        )
        self.assertEqual(
            [r.activity_values["IC50 (nM)"] for r in rows], ["17", "29", "17"]
        )
        self.assertEqual([r.activity_sources[0]["page_no"] for r in rows], [2, 3, 4])

    def test_default_fixes_cannot_split_ids_or_fabricate_values(self):
        row = ActivityRow(cpd="Cpd-1411", activity_values={"IC50": "in", "Dmax": "4]"})
        apply_ocr_fixes(row, DEFAULT_OCR_FIXES, max_cpd_num=141)
        self.assertEqual(row.cpd, "Cpd-1411")
        self.assertEqual(row.activity_values, {"IC50": "in", "Dmax": "4]"})

    def test_infinity_is_not_replaced_with_invented_threshold(self):
        rows = parse_segment(
            "Table 20 assay",
            "[[PAGE 1]]\nTable 20 assay\nCompound No. IC50 (nM)\nCompound 6 ∞",
        )
        self.assertEqual(rows[0].activity_values, {"IC50 (nM)": "∞"})


if __name__ == "__main__":
    unittest.main()
