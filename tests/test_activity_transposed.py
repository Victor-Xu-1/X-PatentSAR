import unittest
from dataclasses import asdict

import fitz

from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.web.artifacts import _activities


def transposed(page, headers):
    xs, ys = [40, 140, 240, 340, 440, 540], [100, 135, 170, 205, 240]
    for i, x in enumerate(xs):
        page.draw_line((x, ys[1] if i in (2, 4) else ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    page.insert_text((40, 80), "Table 31. Paired assays")
    page.insert_text((175, 120), "Caspase activity", fontsize=8)
    page.insert_text((375, 120), "Cytokine release", fontsize=8)
    for row, texts in enumerate(
        [
            ["", *headers],
            ["IC50 (nM)", "2", "300", "4", "600"],
            ["Imax (%)", "80", "90", "70", "95"],
        ],
        1,
    ):
        for col, text in enumerate(texts):
            page.insert_text((xs[col] + 5, ys[row] + 20), text, fontsize=8)


class TransposedActivityTests(unittest.TestCase):
    def test_numeric_dose_headings_are_not_invented_compound_identifiers(self):
        with fitz.open() as doc:
            transposed(doc.new_page(), ["10", "100", "10", "100"])
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(result.rows, [])
        self.assertTrue(any(c["status"] == "unresolved" for c in result.coverage))

    def test_merged_assay_headers_preserve_separate_metrics_and_original_boxes(self):
        with fitz.open() as doc:
            transposed(
                doc.new_page(), ["Compound 17", "Ref. 1", "Compound 17", "Ref. 1"]
            )
            result = extract_coordinate_tables(doc, [0])
        rows = [r for r in result.rows if r.cpd == "Compound 17"]
        self.assertEqual(len(rows), 2)
        projected = [a for row in rows for a in _activities(asdict(row), page_count=1)]
        self.assertEqual([a.value for a in projected], ["2", "80", "4", "70"])
        self.assertIn("Caspase activity", str(rows[0].activity_values))
        self.assertIn("Cytokine release", str(rows[1].activity_values))
        self.assertTrue(all(not r.needs_review for r in rows))
        self.assertEqual(result.owned_pages, {0})

    def test_unproved_named_entities_are_retained_as_unresolved_not_invented_compounds(
        self,
    ):
        with fitz.open() as doc:
            transposed(
                doc.new_page(),
                ["Compound 17", "comparison-X", "Compound 17", "comparison-X"],
            )
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(len(result.rows), 2)
        self.assertTrue(all(r.cpd == "Compound 17" for r in result.rows))
        self.assertEqual(sum(c["status"] == "unresolved" for c in result.coverage), 2)
        root = next(c for c in result.coverage if "transposed_layout" in c)
        self.assertIn("comparison-X", str(root["transposed_layout"]))
        self.assertTrue(
            all(
                "unresolved_columns" not in s
                for r in result.rows
                for s in r.activity_sources
            )
        )
