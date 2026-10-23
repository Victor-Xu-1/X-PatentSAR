"""Generated physical sources: one grid never certifies its entire page."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import original_pdf_reader
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.activity_text_capture import capture_text_page
from patent_sar_extractor.core.activity_text_partition import line_owner, text_partition
from patent_sar_extractor.core.activity_text_sources import text_page_qualified
from patent_sar_extractor.core.source_page_lines import observed_page_text
from patent_sar_extractor.web.artifacts import _activities
from tests.test_activity_parser_modules import draw_grid


def original(
    path, *, literal_first=False, literal=True, grid=True, empty=False, tail=False
):
    with fitz.open() as document:
        page = document.new_page()
        top = 300 if literal_first else 100
        rows = [["No.", "IC50 (nM)"]]
        if not empty:
            rows.append(["31", "9"])
        if grid:
            draw_grid(
                page, rows, caption="Table A. Target: JAK; Assay: binding", top=top
            )
        else:
            # Same native text, glyph positions and extraction order, no rules.
            page.insert_text(
                (60, top - 15), "Table A. Target: JAK; Assay: binding", fontsize=9
            )
            for column in (1, 0):
                for row, cells in enumerate(rows):
                    if cells[column]:
                        page.insert_text(
                            (67 + column * 135, top + row * 25 + 15),
                            cells[column],
                            fontsize=9,
                        )
        if literal:
            page.insert_text(
                (60, 60 if literal_first else 300),
                "Table B. Target: BET; Assay: binding\nNo. | DC50 (nM)\n44 | 0.3",
                fontsize=9,
            )
        if tail:
            page.insert_text((60, 500), "45 | 0.8", fontsize=9)
        document.save(path)


class ActivityMixedOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.primary = self.enterContext(
            patch(
                "patent_sar_extractor.core.page_ocr_cache._build_ocr_engine",
                side_effect=AssertionError("Native ownership checks cannot start OCR"),
            )
        )
        self.auxiliary = self.enterContext(
            patch(
                "patent_sar_extractor.core.text_ocr.runtime.AuxiliaryTextRuntime",
                side_effect=AssertionError("No auxiliary runtime construction"),
            )
        )

    def tearDown(self):
        self.assertEqual(self.primary.call_count, 0)
        self.assertEqual(self.auxiliary.call_count, 0)

    def capture(self, **options):
        pdf = self.root / "original.pdf"
        original(pdf, **options)
        result = extract(str(pdf), {"activity_pages": [0]}, str(self.root / "out"))
        path = self.root / "out/activity_data.json"
        return pdf, result, json.loads(path.read_text())

    def errors(self, data, pdf):
        return activity_evidence_errors(
            data, [0], open_original=original_pdf_reader(pdf)
        )

    def test_both_physical_orders_keep_both_original_tables_and_separate_conditions(
        self,
    ):
        for first in (False, True):
            with self.subTest(literal_first=first):
                pdf, result, data = self.capture(literal_first=first)
                self.assertEqual(
                    {row.cpd for row in result["rows"]}, {"Compound 31", "Compound 44"}
                )
                projected = [
                    a for row in data["rows"] for a in _activities(row, page_count=1)
                ]
                self.assertEqual(
                    {(a.target, a.value) for a in projected},
                    {("JAK", "9"), ("BET", "0.3")},
                )
                self.assertEqual(self.errors(data, pdf), [])

    def test_grid_only_keeps_original_inventory_without_duplicating_measurements(self):
        pdf, result, data = self.capture(literal=False)
        self.assertEqual(result["n_rows"], 1)
        self.assertEqual(len(data["rows"][0]["activity_sources"]), 1)
        coverage = data["coverage"]
        source = coverage["text_sources"]["1"]
        self.assertFalse(coverage["text_pages"]["1"].strip())
        self.assertTrue(source["lines"])
        self.assertTrue(all(line["observations"] for line in source["lines"]))
        self.assertTrue(all(line.get("coordinate_owner") for line in source["lines"]))
        with fitz.open(pdf) as document:
            self.assertEqual(
                source["nomination_text"], document[0].get_text("text").rstrip()
            )
        self.assertEqual(self.errors(data, pdf), [])

    def test_empty_grid_cannot_hide_an_independent_literal_result(self):
        pdf, result, data = self.capture(empty=True)
        self.assertEqual([row.cpd for row in result["rows"]], ["Compound 44"])
        self.assertTrue(
            any(
                r["kind"] == "grid" and r["status"] == "header"
                for r in data["coverage"]["regions"]
            )
        )
        self.assertTrue(self.errors(data, pdf))  # The empty grid is not waived.

    def test_physical_grid_stops_context_even_when_pdf_objects_have_different_order(
        self,
    ):
        pdf, result, data = self.capture(literal_first=True, tail=True)
        self.assertNotIn("Compound 45", {row.cpd for row in result["rows"]})
        self.assertIn("45 | 0.8", data["coverage"]["text_pages"]["1"])
        self.assertTrue(
            any(
                r["kind"] == "text" and r["status"] == "unresolved"
                for r in data["coverage"]["regions"]
            )
        )
        self.assertTrue(self.errors(data, pdf))

    def test_saved_owner_or_outside_line_cannot_be_changed_to_hide_an_original_result(
        self,
    ):
        pdf, _, original_data = self.capture()
        for mutation in (
            "remove_owner",
            "foreign_owner",
            "own_outside",
            "drop_line",
            "move_line",
        ):
            data = copy.deepcopy(original_data)
            lines = data["coverage"]["text_sources"]["1"]["lines"]
            owned = next(line for line in lines if line.get("coordinate_owner"))
            outside = next(line for line in lines if "44" in line["text"])
            if mutation == "remove_owner":
                owned.pop("coordinate_owner")
            elif mutation == "foreign_owner":
                owned["coordinate_owner"]["region_id"] = "f" * 32
            elif mutation == "own_outside":
                outside["coordinate_owner"] = owned["coordinate_owner"]
            elif mutation == "drop_line":
                lines.remove(outside)
            else:
                outside["bbox"] = owned["bbox"]
            with self.subTest(mutation=mutation):
                try:
                    errors = self.errors(data, pdf)
                except (ValueError, TypeError):
                    continue
                self.assertTrue(errors)

    def test_native_text_at_identical_positions_does_not_invent_the_original_grid(self):
        _, _, data = self.capture()
        changed = self.root / "unruled.pdf"
        original(changed, grid=False)
        self.assertTrue(self.errors(data, changed))

    def test_whole_outside_table_and_its_catalog_cannot_be_removed_together(self):
        pdf, _, data = self.capture()
        data["coverage"]["text_pages"] = {}
        data["coverage"]["text_sources"] = {}
        data["coverage"]["regions"] = [
            r for r in data["coverage"]["regions"] if r["kind"] != "text"
        ]
        data["rows"] = [row for row in data["rows"] if row["cpd"] != "Compound 44"]
        self.assertTrue(self.errors(data, pdf))

    def test_partition_is_a_projection_and_does_not_rewrite_any_original_reading(self):
        _, _, data = self.capture()
        source = data["coverage"]["text_sources"]["1"]
        before = copy.deepcopy(source)
        projected, barriers = text_partition(source)
        self.assertEqual(source, before)
        self.assertEqual(projected, data["coverage"]["text_pages"]["1"])
        self.assertTrue(barriers)
        self.assertIn("44 | 0.3", projected)
        self.assertNotIn("31", projected)

    def test_competing_physical_owners_cannot_be_resolved_by_inventory_order(self):
        with fitz.open() as document:
            page = document.new_page()
            draw_grid(page, [["No.", "IC50 (nM)"], ["31", "9"]])
            regions = extract_coordinate_tables(document, [0]).coverage
            duplicate = copy.deepcopy(regions[0])
            duplicate["region_id"] = "f" * 32
            for inventory in ([*regions, duplicate], [duplicate, *regions]):
                source = capture_text_page(
                    page, page.get_text("text"), coordinate_regions=inventory
                )
                self.assertTrue(
                    any(
                        (line.get("coordinate_owner") or {}).get("role") == "ambiguous"
                        for line in source["lines"]
                    )
                )
                self.assertFalse(
                    text_page_qualified(
                        source, observed_page_text(source), coordinate_regions=inventory
                    )
                )

    def test_crossing_a_grid_boundary_is_ambiguous_not_an_outside_table(self):
        with fitz.open() as document:
            page = document.new_page()
            draw_grid(page, [["No.", "IC50 (nM)"], ["31", "9"]])
            regions = extract_coordinate_tables(document, [0]).coverage
            claim = line_owner(
                {"bbox": [50, 105, 350, 117], "text": "No. IC50 (nM)"}, regions
            )
            self.assertEqual(claim["role"], "ambiguous")
            self.assertEqual(claim["region_ids"], [regions[0]["region_id"]])

    def test_untrusted_owner_shapes_are_refused_without_an_attribute_error(self):
        _, _, data = self.capture()
        source = data["coverage"]["text_sources"]["1"]
        for owner in (
            None,
            [],
            True,
            1,
            {"role": "unknown"},
            {"role": [], "region_id": "a" * 32},
        ):
            changed = copy.deepcopy(source)
            changed["lines"][0]["coordinate_owner"] = owner
            with self.subTest(owner=owner):
                self.assertFalse(
                    text_page_qualified(
                        changed,
                        data["coverage"]["text_pages"]["1"],
                        coordinate_regions=data["coverage"]["regions"],
                    )
                )


if __name__ == "__main__":
    unittest.main()
