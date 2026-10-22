"""Complete original wrap proofs, distinct from the locally observed arrows."""

import copy
import unittest
from unittest.mock import patch

import fitz
from native_reaction_consumers import assert_web_original, assert_worker_checkpoint
from native_reaction_support import NativeReactionFixture
from raster_reaction_support import RasterReactionFixture

from patent_sar_extractor.core.heading_declaration_scope import declaration_candidates
from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)
from patent_sar_extractor.core.heading_reaction import reaction_source_status
from patent_sar_extractor.core.reaction_graph import reaction_route
from patent_sar_extractor.core.reaction_page_source import source_page_vectors
from patent_sar_extractor.core.reaction_steps import page_reaction_steps
from patent_sar_extractor.core.source_evidence_identity import proof_id


class ReactionLayoutPortProofTests(NativeReactionFixture, unittest.TestCase):
    def folded(self, *, reverse=False):
        for name, x, y in (
            ("start", 60, 100),
            ("middle", 290, 100),
            ("continued", 290 if reverse else 60, 320),
            ("terminal", 60 if reverse else 290, 320),
        ):
            self.molecule(name, x, y)
        self.arrow((175, 145), (260, 145))
        self.arrow((405, 145), (545, 145))
        self.arrow((260, 365), (175, 365)) if reverse else self.arrow(
            (175, 365), (260, 365)
        )

    def page_input(self, *, previous_arrow=True, previous_output=False):
        self.page.add_redact_annot(fitz.Rect(20, 590, 500, 630))
        self.page.apply_redactions()
        self.pair() if previous_arrow else self.molecule("S2", 280, 100)
        if previous_arrow:
            self.arrow((180, 145), (250, 145))
        if previous_output:
            self.arrow((390, 145), (540, 145))
        self.document.new_page(width=660, height=660)
        self.page = self.document[1]
        self.page.insert_text((35, 610), "Step 1: Preparation", fontsize=11)
        self.molecule("terminal", 280, 100)
        self.structures[-1]["page_no"] = 2
        self.arrow((70, 145), (250, 145))

    def evidence(self, setup=None):
        (setup or self.folded)()
        binding = self.assert_product("terminal")
        source = binding["original_heading_structure_evidence"]
        self.assertEqual(source["reaction_source"]["version"], 5)
        return binding, source

    def test_port_is_still_missing_locally_and_resolution_has_its_own_source_record(
        self,
    ):
        binding, source = self.evidence()
        proof = source["reaction_source"]
        page = proof["pages"][0]
        diagrams = source["declaration_scope"]["pages"][0]["structures"]
        regions = [d["bbox"] for d in diagrams]
        vectors, uncertainty = source_page_vectors(page, regions)
        local = page_reaction_steps(vectors, diagrams, regions, uncertainty)
        opened = [step for step in local["steps"] if step["output_port"] is not None]
        self.assertEqual(
            [(step["from"], step["to"]) for step in opened], [("middle", None)]
        )
        joins = proof["layout_joins"]
        self.assertEqual(len(joins), 1)
        self.assertEqual(joins[0]["resolved_structure_id"], "continued")
        self.assertEqual(joins[0]["port"]["original"], opened[0]["output_port"])
        self.assertEqual(original_heading_source_errors(self.document, [binding]), [])
        self.assertIn(
            "exact original heading and complete replayed reaction-source interpretation",
            binding["evidence_reasons"],
        )

    def test_leftward_following_row_is_resolved_by_its_root_not_position(self):
        binding, _ = self.evidence(lambda: self.folded(reverse=True))
        self.assertEqual(binding["structure_id"], "terminal")

    def test_consecutive_original_page_input_replays_without_ocr(self):
        binding, source = self.evidence(self.page_input)
        join = source["reaction_source"]["layout_joins"][0]
        self.assertEqual(
            (join["kind"], join["resolved_structure_id"]), ("wrapped_page", "S2")
        )
        self.assertEqual(original_heading_source_errors(self.document, [binding]), [])

    def test_mutually_missing_page_ends_are_not_a_molecule(self):
        self.page_input(previous_output=True)
        self.assertEqual(len(self.select()[0]), 0)

    def test_a_shallow_ray_exiting_the_bottom_is_not_a_horizontal_wrap_port(self):
        self.page.set_mediabox(fitz.Rect(0, 0, 2000, 660))
        self.page.add_redact_annot(fitz.Rect(20, 590, 500, 630))
        self.page.apply_redactions()
        self.molecule("start", 60, 560)
        self.molecule("middle", 290, 560)
        self.arrow((175, 605), (260, 605))
        self.arrow((405, 640), (545, 642.5))
        self.document.new_page(width=660, height=660)
        self.page = self.document[1]
        self.page.insert_text((35, 610), "Step 1: Preparation", fontsize=11)
        self.molecule("terminal", 280, 100)
        self.structures[-1]["page_no"] = 2
        self.assertEqual(len(self.select()[0]), 0)

    def test_unowned_previous_page_drawing_does_not_become_a_completed_route(self):
        self.page_input(previous_arrow=False)
        self.assertEqual(len(self.select()[0]), 0)

    def test_an_explicit_alternative_product_is_not_an_implicit_continuation(self):
        self.folded()
        self.page.insert_text((55, 305), "Alternative product", fontsize=11)
        self.assertEqual(len(self.select()[0]), 0)

    def test_an_independent_preparation_cannot_borrow_the_previous_page(self):
        self.page_input()
        self.page.insert_text((35, 40), "Preparation of Compound 038", fontsize=12)
        self.assertEqual(
            [(b["cpd"], b["structure_id"]) for b in self.select()[0]],
            [("Compound 037B", "S2")],
        )

    def test_a_later_extra_route_cannot_be_omitted_to_accept_the_first_wrap(self):
        self.folded()
        self.molecule("other-start", 60, 470)
        self.molecule("other-end", 290, 470)
        self.arrow((175, 515), (260, 515))
        self.assertEqual(len(self.select()[0]), 0)

    def test_rehashed_layout_deletions_types_and_wrong_nodes_are_rejected(self):
        _, source = self.evidence()
        original = source["reaction_source"]
        changes = []
        changed = copy.deepcopy(original)
        changed["layout_joins"] = []
        changes.append(changed)
        changed = copy.deepcopy(original)
        changed["layout_joins"][0]["resolved_structure_id"] = "terminal"
        changes.append(changed)
        changed = copy.deepcopy(original)
        changed["layout_joins"][0]["port"]["page_no"] = True
        changes.append(changed)
        changed = copy.deepcopy(original)
        changed["layout_joins"][0]["port"]["original"]["source_boundary"][0] -= 1
        changes.append(changed)
        for changed in changes:
            changed.pop("identity")
            changed["identity"] = proof_id(changed)
            with (
                self.subTest(join=changed["layout_joins"]),
                self.assertRaises(ValueError),
            ):
                reaction_source_status(
                    changed, source["declaration_scope"], source["heading_source"]
                )

    def test_old_source_versions_cannot_be_retagged_to_accept_wraps(self):
        _, source = self.evidence()
        for version, status in (
            (2, "observed_native_reaction"),
            (4, "observed_source_reaction_roles"),
        ):
            changed = copy.deepcopy(source["reaction_source"])
            changed["version"], changed["status"] = version, status
            del changed["layout_joins"]
            if version == 2:
                del changed["reactant_groups"], changed["input_operators"]
            changed.pop("identity")
            changed["identity"] = proof_id(changed)
            with self.subTest(version=version), self.assertRaises(ValueError):
                reaction_source_status(
                    changed, source["declaration_scope"], source["heading_source"]
                )

    def test_actual_source_ink_is_rechecked_even_if_saved_graph_is_unchanged(self):
        binding, _ = self.evidence()
        self.page.draw_line((580, 140), (580, 150))
        self.assertTrue(original_heading_source_errors(self.document, [binding]))

    def test_an_independent_source_in_the_gap_prevents_a_wrap(self):
        _, source = self.evidence()
        proof, scope = source["reaction_source"], source["declaration_scope"]
        candidates, complete = declaration_candidates(scope, source["heading_source"])
        self.assertTrue(complete)
        vectors, errors = source_page_vectors(
            proof["pages"][0], [c["bbox"] for c in candidates]
        )
        originals = copy.deepcopy((vectors, candidates))
        with self.assertRaisesRegex(ValueError, "independently owned"):
            reaction_route(
                candidates,
                [vectors],
                source_regions={
                    1: [c["bbox"] for c in candidates] + [[0, 230, 660, 250]]
                },
                endpoint_uncertainty={1: errors},
                allow_continuations=True,
            )
        self.assertEqual((vectors, candidates), originals)

    def test_step_budget_refuses_instead_of_trimming_a_route(self):
        self.folded()
        with patch("patent_sar_extractor.core.reaction_layout.MAX_ARROW_COUNT", 2):
            self.assertEqual(len(self.select()[0]), 0)
        self.assert_product("terminal")

    def test_scanned_original_ports_keep_their_pixel_uncertainty(self):
        self.folded()
        RasterReactionFixture.rasterize_route(self)
        binding = self.assert_product("terminal")
        proof = binding["original_heading_structure_evidence"]["reaction_source"]
        self.assertEqual(proof["version"], 5)
        self.assertGreater(
            proof["layout_joins"][0]["port"]["original"]["coordinate_error"], 0
        )
        self.assertEqual(original_heading_source_errors(self.document, [binding]), [])

    def test_normal_worker_checkpoint_and_web_keep_wrapped_source_ownership(self):
        assert_worker_checkpoint(
            self,
            source_setup=self.folded,
            terminal="terminal",
            unassigned=("start", "middle", "continued"),
        )

    def test_shared_web_and_final_qa_require_the_actual_wrapped_original(self):
        assert_web_original(self, source_setup=self.folded, terminal="terminal")


if __name__ == "__main__":
    unittest.main()
