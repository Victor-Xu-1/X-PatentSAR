"""Unused printed pairs and proved many-source/one-primary reprint controls."""

from __future__ import annotations

import unittest
from dataclasses import replace

import fitz
from test_numbered_structure_binding import cell, structure

from patent_sar_extractor.core.numbered_structure_binding import bind_numbered_tables
from patent_sar_extractor.core.numbered_structure_pairs import pair_numbered_table_cells
from patent_sar_extractor.core.structure_catalogs import Catalog


class NumberedSourceEdgeTests(unittest.TestCase):
    def _native_pair(self, with_unlabelled_drawing: bool):
        document = fitz.open()
        page = document.new_page()
        for x in (50, 100, 280, 330, 510):
            page.draw_line((x, 90), (x, 215))
        for y in (90, 115, 215):
            page.draw_line((50, y), (510, y))
        for x, text in (
            (55, "Cmpd No."),
            (150, "Structure"),
            (285, "Cmpd No."),
            (380, "Structure"),
        ):
            page.insert_text((x, 105), text, fontsize=8)
        page.insert_text((60, 140), "17.", fontsize=10)
        bounds = [(110.0, 125.0, 265.0, 205.0)]
        if with_unlabelled_drawing:
            bounds.append((340.0, 125.0, 495.0, 205.0))
        structures = []
        for index, (x0, y0, x1, y1) in enumerate(bounds):
            page.draw_line((x0 + 20, y0 + 20), (x0 + 50, y0 + 40))
            page.draw_line((x0 + 50, y0 + 40), (x0 + 80, y0 + 20))
            structures.append(
                {
                    "id": f"S{index}",
                    "idx": index,
                    "page_no": 1,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "image_path": "not-opened-by-cell-matcher.png",
                }
            )
        return document, structures

    def test_unused_blank_pair_is_not_an_unresolved_identifier(self):
        document, structures = self._native_pair(False)
        with document:
            result = bind_numbered_tables(document, structures, [0], None)
        self.assertEqual([binding.label for binding in result.bindings], ["17"])
        self.assertEqual(result.recognized_pages, (0,))
        self.assertEqual(result.issues, ())

    def test_unlabelled_drawn_structure_is_not_dropped_as_an_unused_pair(self):
        document, structures = self._native_pair(True)
        with document:
            result = bind_numbered_tables(document, structures, [0], None)
        self.assertEqual([binding.label for binding in result.bindings], ["17"])
        self.assertTrue(
            any(issue.reason == "unresolved_label" for issue in result.issues)
        )
        self.assertEqual(result.observed_keys, frozenset({"17"}))

    def test_repeated_selected_reprints_keep_one_primary_and_all_proved_sources(self):
        primary = replace(
            cell("31", 0, page=0),
            catalog=Catalog("Table A", "Complete compounds", False),
        )
        first = replace(
            cell("31", 0, page=1),
            catalog=Catalog("Table B", "Selected compounds", True),
        )
        second = replace(cell("31", 1, page=1), catalog=first.catalog)
        result = pair_numbered_table_cells(
            [primary, first, second],
            [
                structure(primary, name="primary"),
                structure(first, name="reprint-a"),
                structure(second, name="reprint-b"),
            ],
            None,
        )
        self.assertEqual(
            [(row.label, row.structure["id"]) for row in result.bindings],
            [("31", "primary")],
        )
        self.assertEqual(
            {row.structure["id"] for row in result.reprints}, {"reprint-a", "reprint-b"}
        )
        self.assertEqual(result.issues, ())

    def test_duplicate_novel_selected_labels_cannot_acquire_a_primary(self):
        primary = replace(
            cell("31", 0, page=0),
            catalog=Catalog("Table A", "Complete compounds", False),
        )
        first = replace(
            cell("32", 0, page=1),
            catalog=Catalog("Table B", "Selected compounds", True),
        )
        second = replace(cell("32", 1, page=1), catalog=first.catalog)
        result = pair_numbered_table_cells(
            [primary, first, second],
            [
                structure(primary, name="primary"),
                structure(first, name="one"),
                structure(second, name="two"),
            ],
            None,
        )
        self.assertEqual([row.label for row in result.bindings], ["31"])
        self.assertEqual(result.reprints, ())
        self.assertEqual([issue.label for issue in result.issues], ["32", "32"])
        self.assertTrue(
            all(issue.reason == "duplicate_label" for issue in result.issues)
        )


if __name__ == "__main__":
    unittest.main()
