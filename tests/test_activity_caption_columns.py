"""Original caption and context ownership across differing physical columns."""

import copy
import unittest

import fitz

from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_coverage import (
    coverage_errors,
    coverage_packet,
    source_record,
)
from patent_sar_extractor.core.activity_header_evidence import proof_id
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.binding_source_regions import reference_regions
from tests import test_activity_context_windows
from tests.test_activity_parallel_grids import panel


class CaptionColumnOwnershipTests(unittest.TestCase):
    def test_centered_caption_inside_one_table_keeps_its_original_identity(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((100, 80), "Table 91. Target: ALPHA", fontsize=8)
            panel(page, 40, 100, [["No.", "IC50 (nM)", "Dmax (%)"], ["7", "3", "90"]])
            output = extract_coordinate_tables(document, [0])
        self.assertEqual(len(output.rows), 1)
        self.assertEqual(output.rows[0].table_id, "Table 91")
        self.assertEqual(output.rows[0].activity_sources[0]["target"], "ALPHA")

    def test_staggered_parallel_captions_never_relabel_another_table(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 80), "Table 91. Target: ALPHA", fontsize=8)
            page.insert_text((240, 60), "Table 92. Target: BETA", fontsize=8)
            panel(page, 40, 100, [["No.", "IC50 (nM)", "Dmax (%)"], ["7", "3", "90"]])
            panel(page, 240, 100, [["No.", "IC50 (nM)", "Dmax (%)"], ["9", "5", "80"]])
            output = extract_coordinate_tables(document, [0])
        self.assertEqual(len(output.rows), 2)
        self.assertEqual(
            [row.table_id for row in output.rows], ["Table 91", "Table 92"]
        )
        self.assertEqual(
            [row.activity_sources[0]["target"] for row in output.rows],
            ["ALPHA", "BETA"],
        )

    def test_single_shared_caption_still_owns_equal_parallel_panels(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 80), "Table 93. Target: GAMMA", fontsize=8)
            panel(page, 40, 100, [["No.", "IC50 (nM)", "Dmax (%)"], ["7", "3", "90"]])
            panel(page, 240, 100, [["9", "5", "80"], ["12", "6", "75"]])
            output = extract_coordinate_tables(document, [0])
        self.assertEqual(len(output.rows), 3)
        self.assertEqual({row.table_id for row in output.rows}, {"Table 93"})

    def test_shared_caption_above_middle_or_last_panel_keeps_all_three_panels(self):
        for caption_x in (250, 430):
            with self.subTest(caption_x=caption_x), fitz.open() as document:
                page = document.new_page()
                page.insert_text((caption_x, 80), "Table 93. Target: GAMMA", fontsize=8)
                panel(
                    page,
                    40,
                    100,
                    [["No.", "IC50 (nM)", "Dmax (%)"], ["7", "3", "90"]],
                )
                panel(page, 220, 100, [["9", "5", "80"], ["12", "6", "75"]])
                panel(page, 400, 100, [["15", "7", "70"], ["17", "8", "60"]])
                output = extract_coordinate_tables(document, [0])
            self.assertEqual(len(output.rows), 5)
            self.assertEqual({row.table_id for row in output.rows}, {"Table 93"})
            self.assertEqual(
                {row.activity_sources[0]["target"] for row in output.rows},
                {"GAMMA"},
            )

    def test_staggered_grid_heights_do_not_reopen_another_caption_column(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 80), "Table 91. Target: ALPHA", fontsize=8)
            page.insert_text((240, 60), "Table 92. Target: BETA", fontsize=8)
            panel(page, 40, 180, [["No.", "IC50 (nM)", "Dmax (%)"], ["7", "3", "90"]])
            panel(page, 240, 100, [["No.", "IC50 (nM)", "Dmax (%)"], ["9", "5", "80"]])
            output = extract_coordinate_tables(document, [0])
        self.assertEqual(len(output.rows), 2)
        self.assertEqual(
            {row.cpd: row.table_id for row in output.rows},
            {"Compound 7": "Table 91", "Compound 9": "Table 92"},
        )

    def test_local_body_labels_remain_in_their_own_table_column(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((40, 70), "Table 91. Binding", fontsize=8)
            page.insert_text((240, 70), "Table 92. Binding", fontsize=8)
            page.insert_text((40, 85), "Target: ALPHA; Assay: one", fontsize=8)
            page.insert_text((240, 85), "Target: BETA; Assay: two", fontsize=8)
            for x, values in ((40, ["7", "3", "90"]), (240, ["9", "5", "80"])):
                panel(page, x, 100, [["No.", "IC50 (nM)", "Dmax (%)"], values])
            output = extract_coordinate_tables(document, [0])
        self.assertEqual(
            [row.activity_sources[0]["target"] for row in output.rows],
            ["ALPHA", "BETA"],
        )
        self.assertEqual(
            [row.activity_sources[0]["assay"] for row in output.rows], ["one", "two"]
        )

    def test_native_and_raster_parallel_titles_keep_the_same_window(self):
        with fitz.open() as drawing, fitz.open() as document:
            source = drawing.new_page()
            source.insert_text((240, 60), "Table 92. Target: BETA", fontsize=8)
            panel(
                source,
                240,
                100,
                [["No.", "IC50 (nM)", "Dmax (%)"], ["9", "5", "80"]],
            )
            pixels = source.get_pixmap(
                matrix=fitz.Matrix(4, 4), clip=fitz.Rect(210, 0, 450, 600), alpha=False
            )
            page = document.new_page()
            page.insert_text((40, 80), "Table 91. Target: ALPHA", fontsize=8)
            panel(page, 40, 100, [["No.", "IC50 (nM)", "Dmax (%)"], ["7", "3", "90"]])
            page.insert_image(fitz.Rect(210, 0, 450, 600), stream=pixels.tobytes("png"))
            output = extract_coordinate_tables(document, [0])
        self.assertEqual(
            {row.cpd: row.table_id for row in output.rows},
            {"Compound 7": "Table 91", "Compound 9": "Table 92"},
        )
        self.assertTrue(all(not row.needs_review for row in output.rows))

    def test_current_native_inventory_cannot_drop_axes_or_invent_shared_span(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((100, 80), "Table 91. Target: ALPHA", fontsize=8)
            panel(page, 40, 100, [["No.", "IC50 (nM)", "Dmax (%)"], ["7", "3", "90"]])
            parsed = extract_coordinate_tables(document, [0])
        original = coverage_packet([0], parsed.coverage, parsed.rows)
        self.assertEqual(coverage_errors(original, [0], rows=parsed.rows), [])
        for field in ("grid_axes", "context_geometry", "parallel_span"):
            changed = copy.deepcopy(original)
            root = next(
                record for record in changed["regions"] if record["kind"] == "grid"
            )
            if field == "grid_axes":
                del root[field]
            elif field == "context_geometry":
                del root["layout"][field]
            else:
                root["layout"]["context_geometry"][field][1] += 30
            with self.subTest(field=field), self.assertRaises(ValueError):
                coverage_errors(changed, [0], rows=parsed.rows)

    def test_saved_header_cannot_forge_a_shared_span_or_downgrade_its_contract(self):
        fixture = test_activity_context_windows.ActivityContextWindowTests()
        self.addCleanup(fixture.doCleanups)
        original = fixture.raster_artifact()
        self.assertEqual(
            activity_evidence_errors(
                original, [0], open_original=fixture.raster_original
            ),
            [],
        )
        old, proof = next(iter(original["header_observations"].items()))
        self.assertEqual(proof["column_contract"], 5)
        self.assertEqual(proof["original_source"]["schema_version"], 3)
        for invalid in (None, "foreign", []):
            altered = {**proof, "original_source": invalid}
            self.assertFalse(valid_header_proof(altered))
        self.assertFalse(valid_header_proof({**proof, "column_contract": 3}))
        changed = copy.deepcopy(original)
        altered = changed["header_observations"][old]
        altered["original_source"]["context_geometry"]["parallel_span"][1] += 30
        replacement = proof_id(altered)
        changed["header_observations"] = {replacement: altered}
        for row in changed["rows"]:
            for source in row["activity_sources"]:
                if source.get("header_resolution", {}).get("evidence_ref") == old:
                    source["header_resolution"]["evidence_ref"] = replacement
        with self.assertRaisesRegex(ValueError, "physical grid inventory"):
            activity_evidence_errors(changed, [0])

    def test_binding_characterization_uses_the_same_centered_caption_owner(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((80, 80), "Table 91. Characterization", fontsize=8)
            page.insert_text((240, 60), "Table 92. Binding activity", fontsize=8)
            panel(
                page,
                40,
                100,
                [
                    ["No.", "Characterization", "MS (m/z)"],
                    ["7", "1H NMR (400 MHz)", "MS m/z 473"],
                ],
            )
            panel(page, 240, 100, [["No.", "IC50 (nM)", "Dmax (%)"], ["9", "5", "80"]])
            regions = reference_regions(page, original_pdf_sha256="a" * 64)
        self.assertEqual(len(regions), 1)
        self.assertIn("Table 91", regions[0]["role_scope"]["prefix"])
        self.assertNotIn("Table 92", regions[0]["role_scope"]["prefix"])

    def test_unread_number_row_requires_an_actual_parent_not_an_invented_grid(self):
        with fitz.open() as document:
            page = document.new_page()
            panel(
                page,
                40,
                100,
                [["No.", "IC50 (nM)", "Dmax (%)"], ["?", "3", "90"], ["7", "5", "80"]],
            )
            parsed = extract_coordinate_tables(document, [0])
        self.assertEqual([row.cpd for row in parsed.rows], ["Compound 7"])
        original = coverage_packet([0], parsed.coverage, parsed.rows)
        self.assertTrue(coverage_errors(original, [0], rows=parsed.rows))
        child = next(
            record for record in original["regions"] if "parent_grid" in record
        )
        self.assertNotIn("grid_axes", child)
        fake_parent = list(child["parent_grid"])
        fake_parent[2] += 30
        changed = copy.deepcopy(original)
        forged = source_record(
            child["page_no"],
            child["kind"],
            child["bbox"],
            child["table_id"],
            child["header"],
            child["status"],
            child["reason"],
            child["row_count"],
            parent_grid=fake_parent,
        )
        changed["regions"] = [
            forged if record["region_id"] == child["region_id"] else record
            for record in changed["regions"]
        ]
        with self.assertRaisesRegex(ValueError, "exact physical parent"):
            coverage_errors(changed, [0], rows=parsed.rows)


if __name__ == "__main__":
    unittest.main()
