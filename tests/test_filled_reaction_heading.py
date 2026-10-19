"""Actual opaque source heads/shaft roles; never synthetic chemistry acceptance."""

import copy
import unittest

import fitz
from native_reaction_consumers import assert_web_original, assert_worker_checkpoint
from native_reaction_support import NativeReactionFixture

from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)
from patent_sar_extractor.core.ocsr.candidate_coverage import candidate_coverage_errors
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.reaction_graph import terminal_reaction_source
from patent_sar_extractor.core.reaction_heads import MAX_FILLED_HEADS, validate_heads
from patent_sar_extractor.core.reaction_vectors import observe_vectors, validate_vectors
from patent_sar_extractor.core.source_evidence_identity import proof_id


class FilledReactionHeadingTests(NativeReactionFixture, unittest.TestCase):
    def test_one_normal_worker_preserves_filled_roles_and_reuses_only_observations(
        self,
    ):
        assert_worker_checkpoint(self, filled=True)

    def test_web_requires_original_filled_ink_not_a_rehashed_model_packet(self):
        assert_web_original(self, filled=True)

    def test_original_filled_right_head_proves_product(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True)
        binding = self.assert_product("S2")
        source = binding["original_heading_structure_evidence"]["reaction_source"]
        self.assertEqual(len(source["pages"][0]["filled_heads"]), 1)
        self.assertEqual(original_heading_source_errors(self.document, [binding]), [])

    def test_original_filled_left_head_does_not_select_rightmost(self):
        self.pair()
        self.arrow((250, 145), (180, 145), filled=True, outline=False)
        self.assert_product("S1")

    def test_filled_up_head_can_have_a_shaft_ending_at_its_base(self):
        self.molecule("S1", 100, 95)
        self.molecule("S2", 100, 310)
        self.arrow((142, 285), (142, 210), filled=True, stem_inset=7)
        self.assert_product("S1")

    def test_mixed_open_filled_multistep_route_uses_all_drawings(self):
        self.pair()
        self.molecule("S3", 490, 100)
        self.arrow((180, 145), (250, 145))
        self.arrow((390, 145), (460, 145), filled=True, stem_inset=3)
        self.assert_product("S3")

    def test_bidirectional_filled_heads_cannot_prove_one_terminal(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True, opposite_head=True)
        self.assertEqual(self.select()[0], [])

    def test_filled_chemical_wedge_inside_drawing_is_not_a_reaction(self):
        self.pair()
        self.arrow((90, 130), (140, 145), filled=True)
        self.assertEqual(self.select()[0], [])

    def test_an_orphan_drawing_cannot_disappear_from_filled_route(self):
        self.pair()
        self.molecule("S3", 80, 320)
        self.arrow((180, 145), (250, 145), filled=True)
        self.assertEqual(self.select()[0], [])

    def test_unattached_triangle_is_retained_without_inventing_an_arrow(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True)
        self.page.draw_polyline(
            [(170, 310), (177, 314), (170, 318)],
            closePath=True,
            color=None,
            fill=(0, 0, 0),
        )
        source = self.assert_product("S2")["original_heading_structure_evidence"][
            "reaction_source"
        ]
        self.assertEqual(len(source["pages"][0]["filled_heads"]), 2)
        self.assertEqual(
            original_heading_source_errors(self.document, [self.assert_product("S2")]),
            [],
        )

    def test_unattached_triangle_still_blocks_an_actual_arrow_connection(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True)
        self.page.draw_polyline(
            [(258, 141), (266, 145), (258, 149)],
            closePath=True,
            color=None,
            fill=(0, 0, 0),
        )
        self.assertEqual(self.select()[0], [])

    def test_transparent_or_overpainted_heads_stay_unproved(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True, fill_opacity=0.3)
        self.assertEqual(self.select()[0], [])
        self.arrow((180, 145), (250, 145), filled=True)
        self.page.draw_rect(fitz.Rect(240, 135, 255, 155), color=None, fill=(1, 1, 1))
        self.assertEqual(self.select()[0], [])

    def test_a_gap_between_shaft_and_filled_head_is_not_invented_away(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True, stem_inset=11)
        self.assertEqual(self.select()[0], [])

    def test_filled_head_cannot_overlap_a_complete_source_drawing(self):
        self.pair()
        self.arrow((180, 145), (285, 145), filled=True)
        self.assertEqual(self.select()[0], [])

    def test_exact_separately_painted_outline_is_conserved_as_one_head(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True, outline=False)
        self.page.draw_polyline([(243, 149), (250, 145), (243, 141), (243, 149)])
        self.assert_product("S2")

    def test_separately_closed_outline_retains_its_actual_closing_stroke(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True, outline=False)
        self.page.draw_polyline([(243, 149), (250, 145), (243, 141)], closePath=True)
        self.assert_product("S2")

    def test_exact_overdrawn_heads_keep_all_source_fill_observations(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True, outline=False)
        self.page.draw_polyline(
            [(243, 149), (250, 145), (243, 141)],
            closePath=True,
            fill=(0.1, 0.1, 0.1),
            width=3,
        )
        source = self.assert_product("S2")["original_heading_structure_evidence"][
            "reaction_source"
        ]
        self.assertEqual(len(source["pages"][0]["filled_heads"]), 2)

    def test_extra_stroke_or_different_head_cannot_merge_as_an_exact_outline(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True)
        self.page.draw_line((244, 140), (244, 150))
        self.assertEqual(self.select()[0], [])

    def test_curved_filled_boundary_is_not_replaced_with_a_straight_triangle(self):
        self.pair()
        self.page.draw_line((180, 145), (250, 145))
        self.page.draw_bezier(
            (243, 141),
            (250, 141),
            (250, 149),
            (243, 149),
            closePath=True,
            fill=(0, 0, 0),
        )
        self.assertEqual(self.select()[0], [])

    def test_malformed_color_geometry_and_head_inventory_overflow_stay_explicit(self):
        self.arrow((180, 145), (250, 145), filled=True)
        observed = observe_vectors(self.page, list(self.page.rect))
        head = observed["filled_heads"][0]
        for change in (
            {"fill_color": [0, 0, 0, 0]},
            {"fill_color": [False, 0, 0]},
            {"stroke_width": True},
            {"stroke_width": float("nan")},
            {"points": [[1, 1], [2, 2], [3, 3]]},
            {"points": [[-1, 1], [2, 3], [3, 1]]},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_heads([{**head, **change}], observed["page_size"])
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_heads([head] * (MAX_FILLED_HEADS + 1), observed["page_size"])

    def test_unknown_filled_polygon_is_not_coerced_into_a_triangle(self):
        self.pair()
        self.page.draw_line((180, 145), (250, 145))
        self.page.draw_polyline(
            [(242, 141), (250, 141), (250, 149), (242, 149)],
            closePath=True,
            fill=(0, 0, 0),
        )
        self.assertEqual(self.select()[0], [])

    def test_saved_filled_head_rehash_cannot_outvote_the_original_pdf(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True)
        binding = self.assert_product("S2")
        changed = copy.deepcopy(binding)
        packet = changed["original_heading_structure_evidence"]["reaction_source"]
        packet["pages"][0]["filled_heads"][0]["points"][0][0] += 0.1
        packet["identity"] = proof_id(
            {k: v for k, v in packet.items() if k != "identity"}
        )
        self.assertTrue(original_heading_source_errors(self.document, [changed]))

    def test_missing_or_foreign_filled_head_packets_do_not_disable_replay(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True)
        binding = self.assert_product("S2")
        for version in (1, True, 2.0):
            changed = copy.deepcopy(binding)
            packet = changed["original_heading_structure_evidence"]["reaction_source"]
            packet["pages"][0]["version"] = version
            self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])
        changed = copy.deepcopy(binding)
        del changed["original_heading_structure_evidence"]["reaction_source"]["pages"][
            0
        ]["filled_heads"]
        self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])

    def test_filled_original_source_plan_and_final_qa_share_the_same_replay(self):
        pdf, _, metadata, bindings, observations = self.saved_source(filled=True)
        self.assertEqual(
            candidate_coverage_errors(
                self.root, {"input_pdf": str(pdf)}, metadata, bindings, observations
            ),
            [],
        )
        self.page.draw_polyline(
            [(243, 149), (250.1, 145), (243, 141)], closePath=True, fill=(0, 0, 0)
        )
        pdf.write_bytes(self.document.tobytes(no_new_id=True))
        self.assertTrue(
            candidate_coverage_errors(
                self.root, {"input_pdf": str(pdf)}, metadata, bindings, observations
            )
        )

    def test_native_head_observation_uses_rendered_page_coordinates(self):
        self.arrow((180, 145), (250, 145), filled=True)
        self.page.set_rotation(90)
        observed = observe_vectors(self.page, list(self.page.rect))
        validate_vectors(observed)
        points = observed["filled_heads"][0]["points"]
        expected = [
            fitz.Point(x, y) * self.page.rotation_matrix
            for x, y in ((243, 149), (250, 145), (243, 141))
        ]
        self.assertEqual(points, [list(point) for point in expected])

    def test_filled_route_geometry_replays_in_all_rendered_page_rotations(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True, stem_inset=3)
        for angle in (0, 90, 180, 270):
            with self.subTest(rotation=angle):
                self.page.set_rotation(angle)
                observed = observe_vectors(self.page, list(self.page.rect))
                candidates = [
                    {
                        "structure_id": s["id"],
                        "page_no": 1,
                        "inside": True,
                        "bbox": list(
                            fitz.Rect([s[k] for k in ("x0", "y0", "x1", "y1")])
                            * self.page.rotation_matrix
                        ),
                    }
                    for s in self.structures
                ]
                self.assertEqual(terminal_reaction_source(candidates, [observed]), "S2")
