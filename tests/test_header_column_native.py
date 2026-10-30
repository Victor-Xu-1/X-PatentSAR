"""Existing-engine column-header checks on isolated controlled original renders."""

import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.activity_artifacts import save_results
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from tests.activity_source_support import original_coordinate_coverage


class HeaderColumnNativeTests(unittest.TestCase):
    def test_actual_scanned_adapter_writer_and_qa_preserve_first_measurement(self):
        doc, _page, _region = self.render([["No."], ["IC50", "nM"], ["Dmax", "%"]])
        self.addCleanup(doc.close)
        result = extract_coordinate_tables(doc, [1])
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0].cpd, "Compound 79")
        self.assertEqual(
            result.rows[0].activity_values, {"IC50 (nM)": "0.125", "Dmax (%)": "85"}
        )
        self.assertFalse(result.rows[0].needs_review)
        coverage = original_coordinate_coverage(doc, [1], result)
        with tempfile.TemporaryDirectory() as root:
            save_results(
                result.rows,
                Path(root),
                {},
                coverage=coverage,
                header_observations=result.header_observations,
            )
            payload = load_json(Path(root) / "activity_data.json", {})
        self.assertEqual(len(payload["header_observations"]), 1)
        self.assertTrue(activity_evidence_errors(payload, [1]))
        self.assertEqual(
            activity_evidence_errors(
                payload, [1], open_original=lambda: nullcontext(doc)
            ),
            [],
        )

    def render(self, headers):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((40, 100), "Table 91. Binding assay", fontsize=10)
        xs, ys = [40, 105, 240, 375], [120, 180, 205]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for col, lines in enumerate(headers):
            for row, line in enumerate(lines):
                page.insert_text((xs[col] + 8, 134 + row * 13), line, fontsize=9)
        for col, value in enumerate(("79", "0.125", "85")):
            page.insert_text((xs[col] + 8, 195), value, fontsize=9)
        pix = page.get_pixmap(matrix=fitz.Matrix(240 / 72, 240 / 72), alpha=False)
        scanned = doc.new_page()
        scanned.insert_image(scanned.rect, stream=pix.tobytes("png"))
        return doc, scanned, {"xs": xs, "ys": ys}

    def test_small_multiline_headers_and_units_are_column_owned(self):
        doc, page, region = self.render(
            [["No."], ["NEK7", "NanoBiT", "DC50nM"], ["NEK7", "NanoBiT", "Dmax %"]]
        )
        original = grid_schema(
            context_from_text("Table 91. Binding assay"), [["No.", "Noise", "Noise"]]
        )
        with doc:
            result = refine_scanned_header(page, region, original)
        self.assertEqual(result.first_data_row, 1)
        self.assertEqual(
            result.header_resolution["status"],
            "observed_header_consensus",
            result.header_resolution,
        )
        keys = [key for _, key in result.groups[0].value_columns]
        self.assertIn("DC50", keys[0])
        self.assertTrue(keys[0].endswith("(nM)"))
        self.assertTrue(keys[1].endswith("(%)"))
        observations = result.header_resolution["observations"]
        self.assertEqual(len(observations), 2)
        for observed in observations:
            self.assertEqual(len(observed["columns"]), 3)
            self.assertEqual(
                [c["physical_column"] for c in observed["columns"]], [0, 1, 2]
            )
            for column in observed["columns"]:
                self.assertEqual(column["bbox"][1:4:2], [120, 180])
                self.assertTrue(column["parts"])
                self.assertNotIn("0.125", column["raw_text"])

    def test_missing_schema_discovery_is_followed_by_the_same_column_proof(self):
        doc, page, region = self.render([["No."], ["IC50", "nM"], ["Dmax", "%"]])
        with doc:
            result = refine_scanned_header(page, region, None)
        self.assertIsNotNone(result)
        self.assertEqual(result.first_data_row, 1)
        self.assertTrue(result.header_resolution["discovery_observations"])
        self.assertTrue(
            all(o["columns"] for o in result.header_resolution["observations"])
        )

    def test_existing_valid_unit_conflict_cannot_be_repaired_by_optical_majority(self):
        doc, page, region = self.render([["No."], ["IC50", "nM"], ["Dmax", "%"]])
        original = grid_schema(
            context_from_text("Table 91. Binding assay"),
            [["No.", "IC50 (uM)", "Dmax (%)"]],
        )
        with doc:
            result = refine_scanned_header(page, region, original)
        self.assertEqual(result.raw_headers[1], "IC50 (uM)")
        self.assertEqual(result.header_resolution["status"], "unresolved")
        self.assertIn(1, result.header_resolution["conflicting_columns"])

    def test_count_metadata_column_cannot_become_an_activity_by_default(self):
        doc, page, region = self.render([["No."], ["IC50", "nM"], ["n"]])
        with doc:
            result = refine_scanned_header(page, region, None)
        self.assertIsNotNone(result)
        self.assertEqual(result.raw_headers[2].strip().lower(), "n")
        self.assertEqual(len(result.groups[0].value_columns), 1)
        self.assertEqual(result.groups[0].metadata_columns, ((2, "reported_n"),))
        self.assertEqual(
            result.header_resolution["status"], "observed_header_consensus"
        )

    def test_previously_unknown_field_cannot_be_silently_removed_as_metadata(self):
        doc, page, region = self.render([["No."], ["IC50", "nM"], ["n"]])
        original = grid_schema(
            context_from_text("Table 91. Binding assay"), [["No.", "Noise", "Noise"]]
        )
        with doc:
            result = refine_scanned_header(page, region, original)
        self.assertEqual(result.raw_headers[2], "Noise")
        self.assertEqual(result.header_resolution["status"], "unresolved")
        self.assertIn(2, result.header_resolution["conflicting_columns"])
        self.assertEqual(result.groups[0].metadata_columns, ())
        self.assertIn("unknown", result.groups[0].value_columns[1][1].lower())
        self.assertNotIn("IC50", result.groups[0].value_columns[1][1])
