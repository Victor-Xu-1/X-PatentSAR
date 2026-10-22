"""Source dependencies, not subpixel vertical rank, own parallel table execution.

Generated native originals only. No private patent, OCR/OCSR, changed values or
relaxed source/caption/column gates are involved.
"""

import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_coverage import coverage_errors, coverage_packet
from patent_sar_extractor.core.activity_table_scopes import table_scope_groups
from tests.test_activity_parallel_grids import panel


def staggered_original(*, unresolved=False):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 80), "Table 28. Target: kinase Q; Assay: inhibition")
    panel(
        page,
        40,
        100.5,
        [
            ["No.", "IC50 (nM)", "Unknown coefficient" if unresolved else "Dmax (%)"],
            ["7B", "3", "90"],
        ],
    )
    panel(page, 220, 100, [["19C", "5", "80"], ["25A", "6", "75"]])
    panel(page, 400, 99.5, [["31D", "7", "70"], ["42E", "8", "60"]])
    return document


class ActivityPanelOrderTests(unittest.TestCase):
    def test_qualified_left_header_precedes_slightly_higher_parallel_data(self):
        with staggered_original() as document:
            result = extract_coordinate_tables(document, [0])
        self.assertEqual(len(result.rows), 5)
        self.assertTrue(all(not row.needs_review for row in result.rows))
        self.assertTrue(all(row.table_id == "Table 28" for row in result.rows))
        self.assertTrue(all(region["status"] == "parsed" for region in result.coverage))
        self.assertEqual(
            {row.cpd for row in result.rows},
            {f"Compound {label}" for label in ("7B", "19C", "25A", "31D", "42E")},
        )
        self.assertEqual(
            coverage_errors(
                coverage_packet([0], result.coverage, result.rows),
                [0],
                rows=result.rows,
            ),
            [],
        )

    def test_saved_source_family_replays_in_dependency_not_vertical_order(self):
        # Isolate the saved reader even before repairing the producer: only its
        # visitation order is controlled. Actual native grids, fields, original
        # source packets, context and column validation are never mocked.
        def dependency_order(regions, *, key):
            return sorted(regions, key=lambda region: region["xs"][0])

        with (
            staggered_original() as document,
            patch(
                "patent_sar_extractor.core.activity_coordinates.sorted",
                dependency_order,
                create=True,
            ),
        ):
            result = extract_coordinate_tables(document, [0])
        self.assertEqual(len(result.rows), 5)
        for records in (result.coverage, list(reversed(result.coverage))):
            families, invalid = table_scope_groups(records)
            self.assertEqual([record["region_id"] for record in invalid], [])
            self.assertEqual([len(family) for family in families], [3])

    def test_original_unknown_header_still_withholds_parallel_carry(self):
        with staggered_original(unresolved=True) as document:
            result = extract_coordinate_tables(document, [0])
        self.assertEqual(len(result.rows), 1)
        self.assertTrue(result.rows[0].needs_review)
        self.assertEqual(
            sum(region["status"] == "unresolved" for region in result.coverage), 2
        )


if __name__ == "__main__":
    unittest.main()
