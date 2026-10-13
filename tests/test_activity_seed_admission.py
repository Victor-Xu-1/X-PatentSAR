"""Source discovery cannot require an OCR-perfect heading or prefixed row IDs."""

import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.activity_coordinates import coordinate_candidates
from patent_sar_extractor.core.activity_coverage import coverage_errors
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_headers import context_from_text


class ActivitySeedAdmissionTests(unittest.TestCase):
    def test_facade_keeps_numeric_rows_when_cached_caption_is_imperfect(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf, cache = root / "input.pdf", root / "page_ocr_cache.json"
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((40, 85), "Table 73. Binding assay")
                xs, ys = [40, 95, 180], [100, 125, 150, 175]
                for x in xs:
                    page.draw_line((x, ys[0]), (x, ys[-1]))
                for y in ys:
                    page.draw_line((xs[0], y), (xs[-1], y))
                for row, values in enumerate(
                    (("No.", "IC50 (nM)"), ("91", "4"), ("92", "8"))
                ):
                    for col, value in enumerate(values):
                        page.insert_text((xs[col] + 3, ys[row] + 15), value, fontsize=8)
                doc.save(pdf)
            write_json_atomic(
                cache,
                {
                    "page_texts": {"0": "Tabie73. Binding assay No. IC50 nM 91 4 92 8"},
                    "ocr_line_map": {},
                },
            )
            result = extract(
                str(pdf),
                {"activity_pages": [0], "ocr_cache_path": str(cache)},
                str(root / "output"),
            )
            self.assertEqual(
                [r.cpd for r in result["rows"]], ["Compound 91", "Compound 92"]
            )
            self.assertTrue(
                all(r.source == "observed_grid_cells" for r in result["rows"])
            )
            self.assertTrue(all(not r.needs_review for r in result["rows"]))
            self.assertTrue(
                all(c["status"] == "parsed" for c in result["coverage"]["regions"])
            )

    def test_seed_bounds_types_and_duplicate_pages(self):
        self.assertEqual(coordinate_candidates([7, 3, 7]), [3, 7])
        for pages in ([True], [-1], [10000], ["7"]):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                coordinate_candidates(pages)

    def test_observed_caption_retains_raw_spelling(self):
        context = context_from_text("Tabie73. Target binding assay")
        self.assertEqual(context.table_id, "Table 73")
        self.assertEqual(context.raw_caption, "Tabie73. Target binding assay")

    def test_classified_seeds_are_not_vetoed_by_cached_text(self):
        for text in ("Table 2. Reagent amounts 12 mmol", "binding was stable at 40 nM"):
            with self.subTest(text=text):
                self.assertEqual(coordinate_candidates([7]), [7])

    def test_explicit_methods_page_is_recorded_without_invented_measurements(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "input.pdf"
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text(
                    (40, 60),
                    "Example 82: HTRF binding assay\n"
                    "Cells were seeded in plates. Reagent was added.\n"
                    "Plates were incubated before the signal was read.",
                )
                doc.save(pdf)
            result = extract(str(pdf), {"activity_pages": [0]}, str(root / "output"))
            self.assertEqual(result["rows"], [])
            regions = result["coverage"]["regions"]
            self.assertEqual(len(regions), 1)
            self.assertEqual(regions[0]["status"], "context")
            self.assertEqual(regions[0]["reason"], "observed_methods")
            self.assertIn("Example 82", regions[0]["header"])
            self.assertEqual(coverage_errors(result["coverage"], [0]), [])

    def test_method_title_cannot_hide_reported_result_or_unsupported_grid(self):
        for extra in (
            "Results for Compound 11: IC50 = 4 nM.",
            "Table 63. Binding activity\nMaterial code | IC50 (nM)\n12 | 4",
        ):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                pdf = root / "input.pdf"
                with fitz.open() as doc:
                    page = doc.new_page()
                    page.insert_text(
                        (40, 60),
                        "Example 82: HTRF binding assay\nCells were seeded. Reagent was added.\n"
                        + extra,
                    )
                    if extra.startswith("Table"):
                        for x in (40, 120, 220):
                            page.draw_line((x, 150), (x, 210))
                        for y in (150, 180, 210):
                            page.draw_line((40, y), (220, y))
                        page.insert_text((43, 166), "Material code")
                        page.insert_text((123, 166), "IC50 (nM)")
                        page.insert_text((43, 196), "12")
                        page.insert_text((123, 196), "4")
                    doc.save(pdf)
                result = extract(
                    str(pdf), {"activity_pages": [0]}, str(root / "output")
                )
                self.assertTrue(coverage_errors(result["coverage"], [0]))
                self.assertTrue(
                    any(
                        r["status"] == "unresolved"
                        for r in result["coverage"]["regions"]
                    )
                )

    def test_a_grid_is_checked_when_cached_caption_and_metric_are_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf, cache = root / "input.pdf", root / "cache.json"
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((40, 85), "Table 92. Binding assay")
                xs, ys = [40, 95, 180], [100, 125, 150]
                for x in xs:
                    page.draw_line((x, ys[0]), (x, ys[-1]))
                for y in ys:
                    page.draw_line((xs[0], y), (xs[-1], y))
                for row, values in enumerate((("No.", "Ki (nM)"), ("88", "5"))):
                    for col, value in enumerate(values):
                        page.insert_text((xs[col] + 3, ys[row] + 15), value, fontsize=8)
                doc.save(pdf)
            write_json_atomic(
                cache,
                {"page_texts": {"0": "unreadable cached text"}, "ocr_line_map": {}},
            )
            result = extract(
                str(pdf),
                {"activity_pages": [0], "ocr_cache_path": str(cache)},
                str(root / "output"),
            )
            self.assertEqual([r.cpd for r in result["rows"]], ["Compound 88"])
            self.assertEqual(result["rows"][0].activity_values, {"Ki (nM)": "5"})
