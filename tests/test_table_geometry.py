from __future__ import annotations

import unittest

import fitz

from patent_sar_extractor.core.table_geometry import detect_ruled_table_regions


def grid(page, xs, ys):
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))


class SharedTableGeometryTests(unittest.TestCase):
    def test_tall_structure_rows_are_connected_by_complete_vertical_edges(self):
        with fitz.open() as doc:
            page = doc.new_page()
            grid(page, [60, 110, 290, 340, 520], [90, 115, 210, 310, 410])
            found = detect_ruled_table_regions(page, dpi=240)
            self.assertEqual(len(found), 1)
            self.assertEqual(len(found[0]["xs"]), 5)
            self.assertEqual(len(found[0]["ys"]), 5)

    def test_separate_tables_without_connecting_edges_are_not_glued(self):
        with fitz.open() as doc:
            page = doc.new_page()
            for ys in ([90, 115, 140], [280, 305, 330]):
                grid(page, [60, 160, 260], ys)
            found = detect_ruled_table_regions(page, dpi=240)
            self.assertEqual(len(found), 2)


if __name__ == "__main__":
    unittest.main()
