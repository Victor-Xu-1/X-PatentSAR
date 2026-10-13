"""Source discovery cannot require an OCR-perfect heading or prefixed row IDs."""

import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.activity_coordinates import coordinate_candidates
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

    def test_scanned_table_caption_with_bare_numeric_ids_is_not_skipped(self):
        for caption in ("Table 73", "Tabie 73", "Tab1e73", "Table73"):
            with self.subTest(caption=caption):
                text = f"{caption}. Target binding assay No. IC50 nM 91 4 92 8"
                self.assertEqual(coordinate_candidates([7], {"7": text}), [7])

    def test_observed_caption_retains_raw_spelling(self):
        context = context_from_text("Tabie73. Target binding assay")
        self.assertEqual(context.table_id, "Table 73")
        self.assertEqual(context.raw_caption, "Tabie73. Target binding assay")

    def test_amounts_prose_and_misspelt_free_text_are_not_candidate_tables(self):
        for text in ("Table 2. Reagent amounts 12 mmol", "binding was stable at 40 nM"):
            with self.subTest(text=text):
                self.assertEqual(coordinate_candidates([7], {"7": text}), [])
