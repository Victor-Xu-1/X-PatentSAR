"""Controlled hybrid sources: native footer is not whole-page text coverage."""

import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core import page_ocr_cache, table_geometry
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.heading_evidence import original_heading_lines
from patent_sar_extractor.core.table_cells import read_cell


def hybrid_page(*, shadow=""):
    doc = fitz.open()
    original = doc.new_page(width=400, height=600)
    xs, ys = [40, 160, 330], [90, 125, 160, 195]
    for x in xs:
        original.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        original.draw_line((xs[0], y), (xs[-1], y))
    for row, cells in enumerate((("No.", "IC50 (nM)"), ("73", "12.4"), ("58", "9.1"))):
        for column, value in enumerate(cells):
            original.insert_text((xs[column] + 10, ys[row] + 22), value, fontsize=11)
    clip = fitz.Rect(38, 88, 332, 197)
    pixmap = original.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip, alpha=False)
    page = doc.new_page(width=400, height=600)
    page.insert_image(clip, stream=pixmap.tobytes("png"))
    page.insert_text((40, 75), "Table 81. Binding activity", fontsize=11)
    page.insert_text(
        (40, 565), "Original document footer is not table coverage", fontsize=9
    )
    if shadow:
        page.insert_text((170, 147), shadow, fontsize=11, render_mode=3)
    return doc, page


class HybridSourceNativeTests(unittest.TestCase):
    def test_cached_raster_heading_is_not_discarded_by_native_footer(self):
        doc, page = hybrid_page()
        with doc:
            lines = original_heading_lines(page, [(100, "Compound 73: Synthesis")])
        self.assertTrue(any(line["text"] == "Compound 73: Synthesis" for line in lines))
        self.assertTrue(any("footer" in line["text"] for line in lines))

    def test_native_header_unit_conflict_survives_raster_consensus(self):
        doc, page = hybrid_page()
        page.insert_text((170, 112), "IC50 (pM)", fontsize=11, render_mode=3)
        with doc:
            result = extract_coordinate_tables(doc, [page.number])
        self.assertTrue(result.rows)
        self.assertTrue(all(row.needs_review for row in result.rows))

    def test_scanned_table_and_native_footer_both_remain_in_layout_tokens(self):
        doc, page = hybrid_page()
        with doc:
            tokens = table_geometry.page_tokens(page)
        text = " ".join(t["text"] for t in tokens)
        self.assertIn("73", text)
        self.assertIn("IC50", text)
        self.assertIn("footer", text)

    def test_actual_hybrid_coordinate_adapter_reads_original_id_and_values(self):
        doc, page = hybrid_page()
        with doc:
            result = extract_coordinate_tables(doc, [page.number])
        self.assertEqual([r.cpd for r in result.rows], ["Compound 73", "Compound 58"])
        self.assertEqual(
            [r.activity_values for r in result.rows],
            [{"IC50 (nM)": "12.4"}, {"IC50 (nM)": "9.1"}],
        )
        self.assertFalse(any(r.needs_review for r in result.rows))

    def test_page_cache_payload_cannot_claim_footer_as_complete_native_observation(
        self,
    ):
        doc, page = hybrid_page()
        with doc:
            text, lines = page_ocr_cache._page_payload(page, min_native_chars=1)
        self.assertIn("IC50", text)
        self.assertIn("73", text)
        self.assertIn("footer", text)
        self.assertTrue(lines)

    def test_region_cell_reader_does_not_trust_page_level_native_flag(self):
        doc, page = hybrid_page()
        with doc:
            tokens = table_geometry.page_tokens(page)
            result = read_cell(page, (40, 125, 160, 160), tokens, "id", True)
        self.assertEqual(result.value, "73")
        self.assertFalse(result.needs_review)
        self.assertTrue(
            any(o["method"].startswith("cell_ocr_") for o in result.observations)
        )

    def test_valid_native_and_raster_value_disagreement_stays_unresolved(self):
        doc, page = hybrid_page(shadow="12.5")
        with doc:
            tokens = table_geometry.page_tokens(page)
            result = read_cell(page, (160, 125, 330, 160), tokens, "number", True)
        self.assertTrue(result.needs_review)
        self.assertTrue(any(o["text"] == "12.5" for o in result.observations))
        self.assertTrue(any(o["text"] == "12.4" for o in result.observations))

    def test_pure_native_page_and_empty_cell_start_no_ocr(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((80, 150), "Compound 73")
            with (
                patch.object(
                    table_geometry,
                    "ocr_tokens_with_positions",
                    side_effect=AssertionError("Pure native needs no OCR"),
                ),
                patch(
                    "patent_sar_extractor.core.table_cells._ocr_cell",
                    side_effect=AssertionError("Native blank is not a scanned region"),
                ),
            ):
                tokens = table_geometry.page_tokens(page)
                blank = read_cell(page, (200, 125, 330, 160), tokens, "number", True)
            self.assertEqual(blank.value, "")

    def test_rotated_native_words_are_projected_to_the_rendered_grid_frame(self):
        with fitz.open() as doc:
            page = doc.new_page(width=400, height=600)
            page.insert_text((40, 100), "Compound 73")
            page.set_rotation(90)
            native = page.get_text("words")[0]
            expected = fitz.Rect(native[:4]) * page.rotation_matrix
            tokens = table_geometry.page_tokens(page)
        self.assertEqual(tokens[0]["bbox"], list(expected))
