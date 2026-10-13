"""Different patents/layouts share headers only with geometric source proof."""

import unittest

import fitz

from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables


def panel(page, left, top, rows, widths=(35, 65, 60)):
    xs = [left]
    for width in widths:
        xs.append(xs[-1] + width)
    ys = [top + 24 * i for i in range(len(rows) + 1)]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    for j, row in enumerate(rows):
        for i, text in enumerate(row):
            page.insert_text((xs[i] + 3, ys[j] + 14), text, fontsize=7)


class ParallelGridTests(unittest.TestCase):
    def test_parallel_panels_and_all_next_page_columns_keep_header_reference(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((40, 80), "Table 72. Target: JAK; Assay: binding")
            panel(page, 40, 100, [["No.", "IC50 (nM)", "Dmax (%)"], ["7", "3", "90"]])
            panel(page, 220, 100, [["9", "5", "80"], ["12B", "6", "75"]])
            page = doc.new_page()
            panel(page, 40, 90, [["15", "7", "70"], ["16", "8", "60"]])
            panel(page, 220, 90, [["20", "9", "55"], ["21", "10", "50"]])
            result = extract_coordinate_tables(doc, [0])
        self.assertEqual(len(result.rows), 7)
        self.assertTrue(all(row.table_id == "Table 72" for row in result.rows))
        self.assertTrue(all(not row.needs_review for row in result.rows))
        self.assertTrue(
            all(
                row.activity_sources[0]["header_region"]["page_no"] == 1
                for row in result.rows
            )
        )

    def test_changed_widths_new_caption_or_nonadjacent_table_cannot_borrow(self):
        for mode in ("width", "caption", "vertical"):
            with self.subTest(mode=mode), fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((40, 80), "Table 72. Binding assay")
                panel(
                    page, 40, 100, [["No.", "IC50 (nM)", "Dmax (%)"], ["7", "3", "90"]]
                )
                if mode == "caption":
                    page.insert_text((220, 80), "Table 73. Other assay", fontsize=8)
                panel(
                    page,
                    220,
                    300 if mode == "vertical" else 100,
                    [["9", "5", "80"], ["12", "6", "75"]],
                    widths=(55, 45, 60) if mode == "width" else (35, 65, 60),
                )
                result = extract_coordinate_tables(doc, [0])
                self.assertEqual(len(result.rows), 1)
                self.assertTrue(
                    any(c["status"] == "unresolved" for c in result.coverage)
                )
