"""Printed-number catalog precedes activity association; reprints remain sources."""

import unittest

from patent_sar_extractor.core.numbered_structure_binding import (
    NumberedTableCell,
    pair_numbered_table_cells,
)
from patent_sar_extractor.core.structure_catalogs import Catalog


def source(label, page, name="Table A", subset=False):
    cell = NumberedTableCell(
        page - 1,
        0,
        1,
        0,
        label,
        (0, 0, 20, 100),
        (20, 0, 100, 100),
        ({"method": "native_cell", "text": label},),
        True,
        Catalog(name, name, subset),
    )
    segment = {
        "id": f"s-{page}",
        "page_no": page,
        "x0": 25,
        "y0": 10,
        "x1": 90,
        "y1": 90,
    }
    return cell, segment


class CompoundCatalogTests(unittest.TestCase):
    def test_printed_catalog_binds_without_any_activity_list(self):
        a, x = source("1", 1)
        b, y = source("8B", 2)
        result = pair_numbered_table_cells([a, b], [x, y], None)
        self.assertEqual([item.label for item in result.bindings], ["1", "8B"])

    def test_verified_selected_reprint_becomes_additional_source_not_anonymous_row(
        self,
    ):
        a, x = source("1", 1)
        b, y = source("2", 2)
        repeat, z = source("1", 3, "Table B", True)
        result = pair_numbered_table_cells([a, b, repeat], [x, y, z], None)
        self.assertEqual([item.label for item in result.bindings], ["1", "2"])
        self.assertEqual(
            [(item.label, item.structure["id"]) for item in result.reprints],
            [("1", "s-3")],
        )
        self.assertEqual(result.issues, ())

    def test_competing_complete_catalogs_are_not_merged_as_reprints(self):
        a, x = source("1", 1)
        b, y = source("1", 2, "Table B")
        result = pair_numbered_table_cells([a, b], [x, y], None)
        self.assertEqual(result.bindings, ())
        self.assertEqual(result.reprints, ())
        self.assertTrue(
            any(issue.reason == "duplicate_label" for issue in result.issues)
        )

    def test_unproved_or_cross_boundary_source_never_inherits_a_printed_number(self):
        a, x = source("1", 1)
        x["x0"] = 10
        result = pair_numbered_table_cells([a], [x], None)
        self.assertEqual(result.bindings, ())
        self.assertTrue(result.issues)
