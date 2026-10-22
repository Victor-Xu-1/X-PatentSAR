"""Real source/binder controls for local plural references, not ID-only skips."""

import copy
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_group_scope import group_heading_members
from patent_sar_extractor.core.source_cell_tokens import cell_text
from patent_sar_extractor.core.structure_binder import bind
from tests import test_heading_mapping as mapping_controls


class HeadingGroupScopeTests(unittest.TestCase):
    def original(
        self, *, inserted=None, only_one_caption=False, raster=False, shadow_step=False
    ):
        temporary = tempfile.TemporaryDirectory(prefix="original-group-scope-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        pdf, metadata = mapping_controls.HeadingMappingTests().original(
            root, captions=not only_one_caption
        )
        with fitz.open(pdf) as document:
            if inserted:
                location, text = inserted
                document[0].insert_text(location, text, fontsize=11)
            if only_one_caption:
                document[0].insert_text((365, 215), "Compound 17", fontsize=11)
            document.saveIncr()
            if raster:
                scanned = root / "scanned.pdf"
                with fitz.open() as output:
                    page = output.new_page(width=600, height=650)
                    page.insert_image(
                        page.rect,
                        stream=document[0]
                        .get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                        .tobytes("png"),
                    )
                    if shadow_step:
                        page.insert_text(
                            (45, 77), "Step 1: Reaction", fontsize=11, render_mode=3
                        )
                    output.save(scanned)
                pdf = scanned
        result = bind(
            str(pdf), {"bind_workers": 1}, str(root / "bindings"), str(metadata)
        )
        payload = load_json(Path(result["output_files"]["json"]), {})
        section = next(
            section
            for section in payload["source_sections"]
            if section.get("identifiers") == ["17", "18"]
        )
        return payload, section

    def members(self, payload, section):
        return group_heading_members(
            section,
            payload["compound_catalog"]["entries"],
            payload["source_reference_scope"]["original_pdf_sha256"],
        )

    def assert_complete_source_context(self, *, raster):
        payload, section = self.original(raster=raster)
        self.assertEqual(self.members(payload, section), {"17", "18"})
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])
        self.assertEqual(
            {
                row["cpd"]: row["structure_id"]
                for row in payload["compound_catalog"]["entries"]
            },
            {"Compound 18": "S1", "Compound 17": "S2"},
        )

    def test_native_source_context_covers_both_ids_without_using_title_order(self):
        self.assert_complete_source_context(raster=False)

    def test_raster_source_context_covers_both_ids_without_using_title_order(self):
        self.assert_complete_source_context(raster=True)

    def test_procedure_assay_and_independent_same_row_column_do_not_lend_members(self):
        for inserted in (
            ((45, 77), "Step 1: Reaction"),
            ((45, 77), "Example 7: Biological evaluation"),
            ((45, 77), "To a solution of the reagent"),
            ((45, 77), "Alternative product"),
            ((45, 77), "[0042] Independent reaction"),
            ((400, 55), "Compound 99"),
        ):
            with self.subTest(inserted=inserted):
                payload, section = self.original(inserted=inserted)
                self.assertEqual(self.members(payload, section), set())
                self.assertTrue(coverage_errors(payload))
                self.assertTrue(
                    {"Compound 17", "Compound 18"}.issubset(
                        {issue["cpd"] for issue in payload["source_issues"]}
                    )
                )

    def test_later_unrelated_heading_does_not_block_a_complete_earlier_group(self):
        payload, section = self.original(inserted=((45, 300), "Compound 99"))
        self.assertEqual(self.members(payload, section), {"17", "18"})
        self.assertEqual(
            {issue["cpd"] for issue in payload["source_issues"]}, {"Compound 99"}
        )

    def test_missing_caption_is_not_assigned_the_remaining_title_identifier(self):
        payload, section = self.original(only_one_caption=True)
        self.assertEqual(self.members(payload, section), {"17"})
        self.assertEqual(
            [row["cpd"] for row in payload["compound_catalog"]["entries"]],
            ["Compound 17"],
        )
        self.assertEqual(
            {issue["cpd"] for issue in payload["source_issues"]}, {"Compound 18"}
        )
        self.assertTrue(coverage_errors(payload))

    def test_deleting_even_a_resigned_group_context_cannot_become_id_only_coverage(
        self,
    ):
        payload, section = self.original()
        del section["group_context"]
        payload["source_reference_scope"] = reference_scope(payload["source_sections"])
        self.assertEqual(
            {
                issue["cpd"]
                for issue in reference_issues(
                    payload, payload["compound_catalog"]["entries"]
                )
            },
            {"Compound 17", "Compound 18"},
        )
        self.assertTrue(coverage_errors(payload))

    def test_foreign_malformed_or_incomplete_context_never_inherits_current_source(
        self,
    ):
        payload, section = self.original()
        for field, value in (
            ("version", True),
            ("page_no", 2),
            ("original_pdf_sha256", "b" * 64),
            ("source_chunks", []),
        ):
            changed = copy.deepcopy(section)
            changed["group_context"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.members(payload, changed)

    def test_independent_native_context_cannot_be_outvoted_by_raster_headings(self):
        payload, section = self.original(raster=True, shadow_step=True)
        self.assertEqual(self.members(payload, section), set())
        self.assertTrue(coverage_errors(payload))

    def test_weak_original_context_words_cannot_disappear_as_proved_caption_roles(self):
        payload, section = self.original(raster=True)
        changed = copy.deepcopy(section)
        source = changed["group_context"]["source_chunks"][0]["sources"][0]
        self.assertEqual(source["origin"], "raster")
        caption = next(
            part
            for part in source["tokens"]
            if "Compound" in part["text"] and part["bbox"][1] > 190
        )
        caption["confidence"] = 0.5
        source["status"] = "unqualified"
        self.assertEqual(self.members(payload, changed), set())
        self.assertEqual(caption["confidence"], 0.5, "Keep the original uncertainty")
        unknown = copy.deepcopy(section)
        source = unknown["group_context"]["source_chunks"][0]["sources"][0]
        caption = next(
            part
            for part in source["tokens"]
            if "Compound" in part["text"] and part["bbox"][1] > 190
        )
        caption["text"] = caption["text"].replace("Compound", "UnresolvedLabel")
        source["text"] = cell_text(source["tokens"], source["bbox"])
        self.assertEqual(self.members(payload, unknown), set())


if __name__ == "__main__":
    unittest.main()
