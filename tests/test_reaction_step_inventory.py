"""Incomplete original steps remain observable without asserting layout edges."""

import copy
import unittest

import fitz
from native_reaction_support import NativeReactionFixture

from patent_sar_extractor.core.heading_reaction import _bounds
from patent_sar_extractor.core.reaction_page_source import (
    observe_source_page,
    source_page_vectors,
)
from patent_sar_extractor.core.reaction_steps import (
    MAX_REACTION_DIAGRAMS,
    page_reaction_steps,
)


class ReactionStepInventoryTests(NativeReactionFixture, unittest.TestCase):
    def source(self, page_index=0):
        bindings, _ = self.select()
        section = next(
            section
            for section in self.sections
            if section["role"] == "compound_heading"
        )
        heading, scope = section["heading_observation"], section["declaration_scope"]
        metadata = scope["pages"][page_index]
        diagrams = metadata["structures"]
        regions = [diagram["bbox"] for diagram in diagrams]
        source = observe_source_page(
            self.document[page_index],
            _bounds(scope, heading, metadata),
            regions,
        )
        vectors, uncertainty = source_page_vectors(source, regions)
        return bindings, vectors, diagrams, regions, uncertainty

    def report(self, page_index=0):
        bindings, vectors, diagrams, regions, uncertainty = self.source(page_index)
        original = copy.deepcopy((vectors, diagrams, regions, uncertainty))
        report = page_reaction_steps(vectors, diagrams, regions, uncertainty)
        self.assertEqual((vectors, diagrams, regions, uncertainty), original)
        self.assertEqual(report["diagram_ids"], [d["structure_id"] for d in diagrams])
        return bindings, report

    def test_connected_original_step_has_no_open_or_unassigned_source(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        bindings, report = self.report()
        self.assertEqual(len(bindings), 1)
        self.assertEqual(report["unassigned"], [])
        self.assertEqual(
            [(s["from"], s["to"]) for s in report["steps"]], [("S1", "S2")]
        )
        self.assertTrue(
            all(s["input_port"] is s["output_port"] is None for s in report["steps"])
        )

    def test_original_output_port_and_wrapped_interpretation_stay_separate(self):
        self.pair()
        self.molecule("next-row", 70, 320)
        self.molecule("next-end", 280, 320)
        self.arrow((180, 145), (250, 145))
        self.arrow((390, 145), (540, 145))
        self.arrow((180, 365), (250, 365))
        bindings, report = self.report()
        self.assertEqual([b["structure_id"] for b in bindings], ["next-end"])
        self.assertEqual(
            bindings[0]["original_heading_structure_evidence"]["reaction_source"][
                "version"
            ],
            5,
        )
        self.assertEqual(len(report["steps"]), 3)
        opened = [step for step in report["steps"] if step["output_port"] is not None]
        self.assertEqual(len(opened), 1)
        self.assertEqual((opened[0]["from"], opened[0]["to"]), ("S2", None))
        self.assertEqual(opened[0]["output_port"]["source_boundary"], [660, 145])
        self.assertEqual(report["unassigned"], [])

    def test_unassigned_condition_drawing_stays_in_the_complete_inventory(self):
        self.molecule("start", 60, 300)
        self.molecule("target", 450, 300)
        self.molecule("added", 260, 175)
        self.arrow((175, 345), (420, 345))
        bindings, report = self.report()
        self.assertEqual(bindings, [])
        self.assertEqual(report["unassigned"], ["added"])
        self.assertEqual(
            [(s["from"], s["to"]) for s in report["steps"]], [("start", "target")]
        )

    def test_cross_page_interpretation_does_not_fabricate_a_local_source_endpoint(self):
        self.page.add_redact_annot(fitz.Rect(20, 590, 500, 630))
        self.page.apply_redactions()
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.document.new_page(width=660, height=660)
        self.page = self.document[1]
        self.page.insert_text((35, 610), "Step 1: Preparation", fontsize=11)
        self.molecule("next-page", 280, 100)
        self.structures[-1]["page_no"] = 2
        self.arrow((70, 145), (250, 145))
        bindings, report = self.report(1)
        self.assertEqual([b["structure_id"] for b in bindings], ["next-page"])
        self.assertEqual(
            bindings[0]["original_heading_structure_evidence"]["reaction_source"][
                "version"
            ],
            5,
        )
        self.assertEqual(report["page_no"], 2)
        self.assertEqual(report["unassigned"], [])
        step = report["steps"][0]
        self.assertIsNone(step["from"])
        self.assertEqual(step["to"], "next-page")
        self.assertIsNone(step["output_port"])
        self.assertEqual(step["input_port"]["source_boundary"], [0, 145])

    def test_an_ambiguous_visible_endpoint_is_not_relabelled_as_an_open_port(self):
        self.pair()
        self.molecule("rival", 280, 100)
        self.arrow((180, 145), (250, 145))
        with self.assertRaisesRegex(ValueError, "unique local visible drawing"):
            self.report()

    def test_original_connection_ink_is_not_ignored_when_an_endpoint_is_open(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.arrow((390, 145), (540, 145))
        self.page.insert_text((570, 149), "N", fontsize=12)
        with self.assertRaisesRegex(ValueError, "blocked by source ink"):
            self.report()

    def test_invalid_or_over_bound_drawing_inventory_is_not_a_successful_prefix(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        _, vectors, diagrams, regions, uncertainty = self.source()
        for changed in (
            [diagrams[0], diagrams[0]],
            [{**diagrams[0], "structure_id": True}],
            [{"structure_id": "missing-bounds"}],
            [
                {**diagrams[0], "structure_id": f"drawing-{i}"}
                for i in range(MAX_REACTION_DIAGRAMS + 1)
            ],
        ):
            with self.subTest(count=len(changed)), self.assertRaises(ValueError):
                page_reaction_steps(vectors, changed, regions, uncertainty)

    def test_foreign_and_nonfinite_uncertainty_cannot_create_an_open_port(self):
        self.pair()
        self.arrow((390, 145), (540, 145))
        _, vectors, diagrams, regions, _ = self.source()
        for changed in ({True: 0}, {0: float("nan")}, {0: -1}, {1000000: 0}):
            with self.subTest(uncertainty=changed), self.assertRaises(ValueError):
                page_reaction_steps(vectors, diagrams, regions, changed)


if __name__ == "__main__":
    unittest.main()
