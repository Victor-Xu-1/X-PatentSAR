"""Real PDF geometry regressions; synthetic cells never stand in for patent QA."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_extractor import (
    ActivityRow,
    _extract_english_biology_activity_rows_from_ocr,
    _merge_activity_rows,
    extract,
)
from patent_sar_extractor.core.table_cells import read_cell


def table(page, xs, ys, cells):
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    # Deliberately insert by column in reverse order. PDF/OCR observation order
    # is not row/column ownership and must never change the extracted values.
    for column in reversed(range(len(xs) - 1)):
        for row, values in enumerate(cells):
            page.insert_text(
                (xs[column] + 8, ys[row] + 15), values[column], fontsize=10
            )


class BiologyActivityTableTests(unittest.TestCase):
    def test_cell_owned_pages_do_not_enter_competing_ocr_parsers(self):
        with tempfile.TemporaryDirectory() as temporary:
            original = Path(temporary) / "controlled.pdf"
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text(
                    (70, 80), "Table 52. Cereblon binding measured in the HTRF assay"
                )
                table(
                    page,
                    [70, 190, 300, 410],
                    [100, 125, 150],
                    [["Example ID", "Ratio", "Grade"], ["37A", "0.15", "++"]],
                )
                doc.save(original)
            with (
                patch(
                    "patent_sar_extractor.core.activity_extractor._load_ocr_engine",
                    return_value=None,
                ),
                patch(
                    "patent_sar_extractor.core.activity_extractor._extract_ruled_activity_rows",
                    return_value=[],
                ) as competing,
            ):
                result = extract(
                    str(original),
                    {
                        "activity_pages": [0],
                        "cpd_pattern": r"Example\s*\d+",
                        "patent_id": "CONTROLLED",
                    },
                    str(Path(temporary) / "activity"),
                )
            self.assertEqual(competing.call_args.args[1], [])
            self.assertEqual(result["n_unique_cpds"], 1)
            self.assertEqual(
                result["rows"][0].activity_values["Cereblon HTRF ratio"], "0.15"
            )

    def test_printed_cross_count_uses_real_rendered_cell_not_collapsed_ocr(self):
        for count in (1, 2, 3):
            with self.subTest(count=count), fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((90, 115), "+" * count, fontsize=12)
                result = read_cell(
                    page,
                    (70, 95, 170, 125),
                    [{"text": "+", "x": 100, "y": 110}],
                    "plus",
                    False,
                )
                self.assertEqual(result.value, "+" * count)
                self.assertFalse(result.needs_review)

    def test_conflicting_cell_readings_remain_review_only(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((90, 115), "31", fontsize=12)
            with patch(
                "patent_sar_extractor.core.table_cells._ocr_cell",
                side_effect=[("36", 0.99), ("37", 0.99)],
            ):
                result = read_cell(
                    page,
                    (70, 95, 170, 125),
                    [{"text": "31", "x": 100, "y": 110}],
                    "id",
                    False,
                )
            self.assertTrue(result.needs_review)
            self.assertEqual(len(result.observations), 3)

    def test_merge_retains_each_assays_distinct_original_page_evidence(self):
        sources = [
            {"page_no": 1, "table_id": "Table 52"},
            {"page_no": 2, "table_id": "Table 54"},
        ]
        rows = _merge_activity_rows(
            [
                ActivityRow(
                    cpd="Example 31",
                    activity_values={"HTRF ratio": "0.1"},
                    activity_sources=[sources[0]],
                ),
                ActivityRow(
                    cpd="Example 31",
                    activity_values={"Degradation grade": "A"},
                    activity_sources=[sources[1]],
                ),
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].activity_sources, sources)

    def test_missing_native_activity_value_is_not_accepted_as_empty_success(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (70, 80), "Table 52. Cereblon binding measured in the HTRF assay"
            )
            table(
                page,
                [70, 190, 300, 410],
                [100, 125, 150],
                [["Example ID", "Ratio", "Grade"], ["37A", "", "++"]],
            )
            rows = _extract_english_biology_activity_rows_from_ocr(doc, [0])
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0].needs_review)

    def test_geometry_prevents_cross_row_ratio_and_grade_shift(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (70, 80), "Table 13. Cereblon binding measured in the HTRF assay"
            )
            table(
                page,
                [70, 190, 300, 410],
                [100, 125, 150, 175],
                [
                    ["Example ID", "Ratio", "Grade"],
                    ["31", "0.07", "+++"],
                    ["46", "0.23", "+"],
                ],
            )
            rows = _extract_english_biology_activity_rows_from_ocr(doc, [0])
            self.assertEqual([r.cpd for r in rows], ["Compound 31", "Compound 46"])
            self.assertEqual(
                rows[0].activity_values,
                {
                    "Cereblon HTRF ratio": "0.07",
                    "Cereblon HTRF grade": "+++",
                },
            )
            self.assertEqual(rows[1].activity_values["Cereblon HTRF ratio"], "0.23")
            self.assertEqual(rows[1].activity_values["Cereblon HTRF grade"], "+")

    def test_assay_headers_not_hardcoded_table_numbers_define_schema(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (70, 80), "Table 52. Cereblon binding measured in the HTRF assay"
            )
            table(
                page,
                [70, 190, 300, 410],
                [100, 125, 150],
                [
                    ["Example ID", "Ratio", "Grade"],
                    ["37A", "0.15", "++"],
                ],
            )
            rows = _extract_english_biology_activity_rows_from_ocr(doc, [0])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].cpd, "Compound 37A")
            self.assertEqual(rows[0].table_id, "Table 52")

    def test_two_id_grade_pairs_preserve_cell_ownership_and_continuation(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text(
                (70, 65),
                "KP4 cells were treated. Protein degradation by Western blot assay.",
            )
            page.insert_text(
                (70, 80), "Table 54. Protein degradation measured by Western blot assay"
            )
            table(
                page,
                [70, 170, 270, 370, 470],
                [100, 125, 150],
                [
                    ["Example ID", "HuR degradation", "Example ID", "HuR degradation"],
                    ["31", "A", "32", "D"],
                ],
            )
            page = doc.new_page()
            table(
                page,
                [70, 170, 270, 370, 470],
                [75, 100, 125],
                [
                    ["33", "B", "34", "C"],
                    ["35", "A", "36", "D"],
                ],
            )
            rows = _extract_english_biology_activity_rows_from_ocr(doc, [0, 1])
            self.assertEqual(
                [r.cpd for r in rows], [f"Compound {n}" for n in range(31, 37)]
            )
            self.assertEqual(
                [r.activity_values["KP4 HuR degradation grade"] for r in rows],
                list("ADBCAD"),
            )
            self.assertEqual(rows[2].page_no, 2)


if __name__ == "__main__":
    unittest.main()
