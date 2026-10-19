"""Actual vector-arrow direction, not position or model-graph product guesses."""

import copy
import unittest

import fitz
from native_reaction_consumers import assert_web_original, assert_worker_checkpoint
from native_reaction_support import NativeReactionFixture

from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.source_evidence_identity import proof_id


class NativeReactionHeadingTests(NativeReactionFixture, unittest.TestCase):
    def test_original_right_arrow_proves_its_product(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.assert_product("S2")

    def test_original_left_arrow_selects_left_product_not_rightmost(self):
        self.pair()
        self.arrow((250, 145), (180, 145))
        self.assert_product("S1")

    def test_original_up_arrow_selects_top_product_not_last(self):
        self.molecule("S1", 100, 95)
        self.molecule("S2", 100, 310)
        self.arrow((142, 285), (142, 210))
        self.assert_product("S1")

    def test_entire_connected_multi_step_route_selects_only_terminal(self):
        self.pair()
        self.molecule("S3", 490, 100)
        self.arrow((180, 145), (250, 145))
        self.arrow((390, 145), (460, 145))
        self.assert_product("S3")

    def test_two_drawings_without_direction_evidence_stay_unassigned(self):
        self.pair()
        self.assertEqual(self.select()[0], [])

    def test_bidirectional_arrow_does_not_have_a_proved_terminal(self):
        self.pair()
        self.arrow((180, 145), (250, 145), opposite_head=True)
        self.assertEqual(self.select()[0], [])

    def test_an_unconnected_candidate_cannot_be_discarded_for_uniqueness(self):
        self.pair()
        self.molecule("S3", 80, 320)
        self.arrow((180, 145), (250, 145))
        self.assertEqual(self.select()[0], [])

    def test_independent_two_terminal_routes_stay_unassigned(self):
        self.pair()
        self.molecule("S3", 70, 320)
        self.molecule("S4", 280, 320)
        self.arrow((180, 145), (250, 145))
        self.arrow((180, 365), (250, 365))
        self.assertEqual(self.select()[0], [])

    def test_altered_saved_arrow_direction_is_not_current_binding_proof(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        binding = self.assert_product("S2")
        changed = copy.deepcopy(binding)
        observation = changed["original_heading_structure_evidence"]["reaction_source"]
        observation["pages"][0]["segments"][0][0] += 10
        self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])

    def test_rehashed_saved_ink_still_requires_the_actual_original(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        binding = self.assert_product("S2")
        self.assertEqual(original_heading_source_errors(self.document, [binding]), [])
        changed = copy.deepcopy(binding)
        observation = changed["original_heading_structure_evidence"]["reaction_source"]
        # A molecule-internal stroke does not alter the geometric route, but it
        # is not the recorded original. A self-computed digest grants no trust.
        observation["pages"][0]["segments"][0][0] += 1
        observation["identity"] = proof_id(
            {k: v for k, v in observation.items() if k != "identity"}
        )
        self.assertTrue(original_heading_source_errors(self.document, [changed]))

    def test_stripping_the_packet_cannot_disable_original_replay(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        changed = self.assert_product("S2")
        del changed["original_heading_structure_evidence"]["reaction_source"]
        self.assertTrue(original_heading_source_errors(self.document, [changed]))
        self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])

    def test_raster_ink_over_the_vector_arrow_cannot_be_ignored(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        pixels = self.page.get_pixmap(clip=fitz.Rect(175, 135, 255, 155))
        self.page.insert_image(
            fitz.Rect(175, 135, 255, 155), stream=pixels.tobytes("png")
        )
        self.assertEqual(self.select()[0], [])

    def test_arrowhead_beyond_the_procedure_boundary_is_not_a_full_route(self):
        self.molecule("S1", 100, 430)
        self.molecule("S2", 350, 530)
        self.arrow((205, 500), (340, 620))
        self.assertEqual(self.select()[0], [])

    def test_drawn_bonds_inside_molecules_are_not_reaction_edges(self):
        self.pair()
        self.arrow((90, 130), (140, 145))
        self.assertEqual(self.select()[0], [])

    def test_conditions_crossing_a_connection_do_not_grant_ownership(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.page.insert_text((257, 149), "N", fontsize=12)
        self.assertEqual(self.select()[0], [])

    def test_an_invisible_native_heading_cannot_name_a_visible_route(self):
        self.page.add_redact_annot(fitz.Rect(20, 20, 450, 48))
        self.page.apply_redactions()
        self.page.insert_text(
            (35, 40), "Preparation of Compound 037B", fontsize=12, render_mode=3
        )
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.assertEqual(len(self.select()[0]), 0)

    def test_a_white_overpainted_heading_cannot_name_a_route(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.page.draw_rect(fitz.Rect(20, 20, 450, 48), color=None, fill=(1, 1, 1))
        self.assertEqual(len(self.select()[0]), 0)

    def test_a_crossing_stroke_is_not_ignored_like_an_empty_cell_frame(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.page.draw_line((170, 35), (210, 35), width=3)
        self.assertEqual(len(self.select()[0]), 0)

    def test_standalone_and_route_share_the_same_visible_heading_gate(self):
        self.molecule("S1", 70, 100)
        self.page.draw_rect(fitz.Rect(20, 20, 450, 48), color=None, fill=(1, 1, 1))
        self.assertEqual(len(self.select()[0]), 0)

    def test_original_replay_checks_literal_heading_not_only_vector_positions(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        binding = self.assert_product("S2")
        self.page.add_redact_annot(fitz.Rect(20, 20, 450, 48))
        self.page.apply_redactions()
        self.page.insert_text((35, 40), "Preparation of Compound 038B", fontsize=12)
        self.assertTrue(original_heading_source_errors(self.document, [binding]))

    def test_normal_source_plan_and_final_qa_replay_the_original_route(self):
        from patent_sar_extractor.core.ocsr.candidate_coverage import (
            candidate_coverage_errors,
        )

        pdf, _, metadata, bindings, observations = self.saved_source()
        self.assertEqual(
            [r["cpd_id"] for r in observations["records"]], ["Compound 037B"]
        )
        self.assertEqual([r["cpd_id"] for r in observations["candidate_records"]], [""])
        self.assertEqual(
            candidate_coverage_errors(
                self.root, {"input_pdf": str(pdf)}, metadata, bindings, observations
            ),
            [],
        )

    def test_one_normal_worker_keeps_reactant_unassigned_and_resumes_without_inference(
        self,
    ):
        assert_worker_checkpoint(self)

    def test_web_reader_requires_safe_original_and_rejects_rehashed_foreign_ink(self):
        assert_web_original(self)


if __name__ == "__main__":
    unittest.main()
