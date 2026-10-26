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
    def test_invalid_column_policy_fails_before_any_page_render(self):
        for value in (True, False, 0, -1, 65, 1.0, "1", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                detect_ruled_table_regions(object(), minimum_columns=value)

    def test_caption_consumer_can_request_a_complete_single_column_grid(self):
        for ys in ([100, 125], [100, 125, 205]):
            with self.subTest(ys=ys), fitz.open() as doc:
                page = doc.new_page()
                grid(page, [40, 200], ys)
                self.assertEqual(detect_ruled_table_regions(page, dpi=240), [])
                found = detect_ruled_table_regions(page, dpi=240, minimum_columns=1)
                self.assertEqual(len(found), 1)
                self.assertEqual(len(found[0]["xs"]), 2)
                self.assertEqual(len(found[0]["ys"]), len(ys))

    def test_single_column_nomination_never_completes_an_open_outer_edge(self):
        for missing in (40, 200):
            with self.subTest(missing=missing), fitz.open() as doc:
                page = doc.new_page()
                for y in (100, 125, 205):
                    page.draw_line((40, y), (200, y))
                for x in (40, 110, 200):
                    if x != missing:
                        page.draw_line((x, 100), (x, 205))
                self.assertEqual(
                    detect_ruled_table_regions(page, dpi=240, minimum_columns=1), []
                )

    def test_single_row_grid_is_detected_independently_of_page_size(self):
        for height in (400, 842, 1600):
            with self.subTest(height=height), fitz.open() as doc:
                page = doc.new_page(width=600, height=height)
                grid(page, [40, 75, 140, 200], [100, 124])
                found = detect_ruled_table_regions(page, dpi=240)
                self.assertEqual(len(found), 1)
                self.assertEqual(len(found[0]["xs"]), 4)
                self.assertEqual(len(found[0]["ys"]), 2)

    def test_short_open_frames_underlines_and_diagrams_are_not_completed(self):
        for mode in ("left_missing", "right_missing", "marks", "underline"):
            with self.subTest(mode=mode), fitz.open() as doc:
                page = doc.new_page()
                for y in (100, 124):
                    page.draw_line((40, y), (200, y))
                xs = [40, 75, 140, 200]
                if mode == "left_missing":
                    xs = xs[1:]
                elif mode == "right_missing":
                    xs = xs[:-1]
                elif mode == "underline":
                    xs = []
                for x in xs:
                    page.draw_line(
                        (x, 106 if mode == "marks" else 100),
                        (x, 118 if mode == "marks" else 124),
                    )
                self.assertEqual(detect_ruled_table_regions(page, dpi=240), [])

    def test_body_separators_below_merged_header_are_retained(self):
        with fitz.open() as doc:
            page = doc.new_page()
            grid(page, [60, 160, 360, 560], [90, 125, 160, 195, 230])
            for x in (260, 460):
                page.draw_line((x, 125), (x, 230))
            found = detect_ruled_table_regions(page, dpi=240)
            self.assertEqual(len(found), 1)
            self.assertEqual(len(found[0]["xs"]), 6)

    def test_short_marks_inside_cells_are_not_column_separators(self):
        with fitz.open() as doc:
            page = doc.new_page()
            grid(page, [60, 200, 340], [90, 130, 170, 210])
            page.draw_line((140, 145), (140, 205))
            found = detect_ruled_table_regions(page, dpi=240)
            self.assertEqual(len(found[0]["xs"]), 3)

    def test_finely_dotted_rules_keep_every_physical_column_and_row(self):
        with fitz.open() as doc:
            page = doc.new_page()
            xs, ys = [60, 85, 120, 155, 205], [90, 120, 133, 146, 159, 172, 185]
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]), width=0.5, dashes="[0.8 0.6] 0")
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y), width=0.5, dashes="[0.8 0.6] 0")
            found = detect_ruled_table_regions(page, dpi=240)
            self.assertEqual(len(found), 1)
            self.assertEqual(len(found[0]["xs"]), len(xs))
            self.assertEqual(len(found[0]["ys"]), len(ys))

    def test_tall_structure_rows_are_connected_by_complete_vertical_edges(self):
        with fitz.open() as doc:
            page = doc.new_page()
            grid(page, [60, 110, 290, 340, 520], [90, 115, 210, 310, 410])
            found = detect_ruled_table_regions(page, dpi=240)
            self.assertEqual(len(found), 1)
            self.assertEqual(len(found[0]["xs"]), 5)
            self.assertEqual(len(found[0]["ys"]), 5)

    def test_separate_tables_without_connecting_edges_are_not_glued(self):
        for gap in (12, 20, 44, 140):
            with self.subTest(gap=gap), fitz.open() as doc:
                page = doc.new_page()
                for ys in ([90, 115, 140], [140 + gap, 165 + gap, 190 + gap]):
                    grid(page, [60, 160, 260], ys)
                found = detect_ruled_table_regions(page, dpi=240)
                self.assertEqual(len(found), 2)

    def test_a_short_row_gap_with_continuous_outer_edges_is_one_table(self):
        for gap in (12, 20, 44):
            with self.subTest(gap=gap), fitz.open() as doc:
                page = doc.new_page()
                grid(page, [60, 160, 260], [90, 115, 140, 140 + gap, 190 + gap])
                found = detect_ruled_table_regions(page, dpi=240)
                self.assertEqual(len(found), 1)
                self.assertEqual(len(found[0]["ys"]), 5)


if __name__ == "__main__":
    unittest.main()
