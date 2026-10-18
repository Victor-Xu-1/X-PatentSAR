"""Registered foreign columns constrain headings without losing raw diagrams."""

import copy
import unittest

from lateral_structure_support import LateralStructureControls

from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_declaration_scope import declaration_candidates
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy


class HeadingColumnScopeTests(LateralStructureControls, unittest.TestCase):
    def test_unruled_catalogue_preparation_uses_its_actual_row_observation_contract(
        self,
    ):
        def preparation(document, records):
            page = document.new_page(width=660, height=720)
            page.insert_text((40, 60), "Compound 73: Preparation", fontsize=11)
            self.add_drawing(page, records, 40, 190, "PREPARATION-73")
            page.insert_text((40, 350), "Step 1: Preparation", fontsize=11)

        _, payload = self.run_case(ruled=False, mutate_document=preparation)
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])
        plan = recognition_inputs(payload)
        self.assertEqual(len(plan.formal), 4)
        self.assertEqual([r["structure_id"] for r in plan.reprints], ["PREPARATION-73"])

    def test_native_and_scanned_parallel_columns_keep_all_original_candidates(self):
        for ruled in (False, True):
            for raster in (False, True):
                with self.subTest(ruled=ruled, raster=raster):
                    _, payload = self.run_case(
                        later_product=True, ruled=ruled, raster=raster
                    )
                    self.assertEqual(coverage_errors(payload), [])
                    binding = next(
                        r
                        for r in payload["final_bindings"]
                        if r["cpd"] == "Compound B80"
                    )
                    evidence = binding["original_heading_structure_evidence"]
                    self.assertEqual(evidence["version"], 5)
                    scope = evidence["declaration_scope"]
                    self.assertEqual(scope["version"], 2)
                    self.assertIn(
                        "C0-A17",
                        {r["structure_id"] for r in scope["pages"][0]["structures"]},
                    )
                    candidates, complete = declaration_candidates(
                        scope, evidence["heading_source"]
                    )
                    self.assertTrue(complete)
                    self.assertEqual(
                        [r["structure_id"] for r in candidates], ["LATER-B80"]
                    )

    def test_omitted_foreign_or_changed_column_packets_cannot_grant_uniqueness(self):
        _, payload = self.run_case(later_product=True)
        source = next(
            r for r in payload["final_bindings"] if r["cpd"] == "Compound B80"
        )
        for mutation in ("omitted", "identity", "document", "raw_inventory"):
            changed = copy.deepcopy(source)
            scope = changed["original_heading_structure_evidence"]["declaration_scope"]
            if mutation == "omitted":
                scope["column_sources"] = []
            elif mutation == "identity":
                scope["column_sources"][0]["region_id"] = "0" * 64
            elif mutation == "document":
                scope["column_sources"][0]["source"]["header_scope"][
                    "original_pdf_sha256"
                ] = "0" * 64
            else:
                scope["pages"][0]["structures"] = [
                    r
                    for r in scope["pages"][0]["structures"]
                    if r["structure_id"] != "C0-A17"
                ]
            with self.subTest(mutation=mutation):
                self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])

    def test_an_unassigned_own_column_diagram_still_blocks_a_singleton(self):
        def extra(document, records):
            self.add_drawing(document[0], records, 360, 625, "OWN-COLUMN-RIVAL")

        _, payload = self.run_case(later_product=True, mutate_document=extra)
        self.assertNotIn("Compound B80", {r["cpd"] for r in payload["final_bindings"]})
        self.assertTrue(coverage_errors(payload))

    def test_registered_foreign_diagram_ink_is_not_an_own_reaction_arrow(self):
        def route(document, records):
            page = document[0]
            self.add_drawing(page, records, 360, 650, "TERMINAL-B80")
            page.draw_line((520, 565), (520, 590))
            page.draw_polyline([(516, 583), (520, 590), (524, 583)])
            # Arrow-like source ink inside an independently proved foreign
            # molecular drawing is retained, not a reaction edge in this lane.
            page.draw_line((160, 510), (215, 510))
            page.draw_polyline([(208, 506), (215, 510), (208, 514)])

        _, payload = self.run_case(later_product=True, mutate_document=route)
        binding = next(
            (r for r in payload["final_bindings"] if r["cpd"] == "Compound B80"), None
        )
        self.assertIsNotNone(binding)
        self.assertEqual(binding["structure_id"], "TERMINAL-B80")
        self.assertEqual(coverage_errors(payload), [])

    def test_a_foreign_closing_procedure_does_not_manufacture_a_singleton(self):
        def close_other_column(document, records):
            document[0].insert_text((50, 570), "Example 91: Preparation", fontsize=10)
            self.add_drawing(document[0], records, 360, 650, "AFTER-FOREIGN-STOP")

        _, payload = self.run_case(
            later_product=True, mutate_document=close_other_column
        )
        self.assertNotIn("Compound B80", {r["cpd"] for r in payload["final_bindings"]})
        section = next(
            s for s in payload["source_sections"] if s.get("identifier") == "B80"
        )
        self.assertEqual(
            section["declaration_scope"]["stop"]["kind"], "foreign_column_boundary"
        )
        self.assertIn(
            "AFTER-FOREIGN-STOP",
            {
                r["structure_id"]
                for r in section["declaration_scope"]["pages"][0]["structures"]
            },
        )

    def test_a_contained_other_column_step_does_not_truncate_the_window(self):
        def other_step(document, records):
            document[0].insert_text((50, 570), "Step 1: Preparation", fontsize=10)
            self.add_drawing(document[0], records, 360, 650, "AFTER-OTHER-STEP")

        _, payload = self.run_case(later_product=True, mutate_document=other_step)
        section = next(
            s for s in payload["source_sections"] if s.get("identifier") == "B80"
        )
        scope = section["declaration_scope"]
        self.assertEqual(scope["stop"]["kind"], "document_end")
        candidates, complete = declaration_candidates(
            scope, section["heading_observation"]
        )
        self.assertTrue(complete)
        self.assertEqual(
            {r["structure_id"] for r in candidates}, {"LATER-B80", "AFTER-OTHER-STEP"}
        )
        self.assertNotIn("Compound B80", {r["cpd"] for r in payload["final_bindings"]})
