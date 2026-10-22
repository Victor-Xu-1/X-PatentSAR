"""Actual scanned route pixels, not OCR/model votes or positional ranking."""

import copy
import unittest

import fitz
from native_reaction_consumers import assert_web_original, assert_worker_checkpoint
from raster_reaction_support import RasterReactionFixture

from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.source_evidence_identity import proof_id


class RasterReactionHeadingTests(RasterReactionFixture, unittest.TestCase):
    def test_current_visible_raster_direction_outvotes_no_hidden_native_path(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        with fitz.open() as overlay:
            page = overlay.new_page(width=660, height=660)
            page.draw_line((250, 145), (180, 145))
            page.draw_polyline([(187, 141), (180, 145), (187, 149)])
            bounds = fitz.Rect(175, 135, 255, 155)
            pixels = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=bounds, alpha=False)
            self.page.insert_image(bounds, stream=pixels.tobytes("png"))
        binding = self.assert_product("S1")
        self.assertEqual(
            binding["original_heading_structure_evidence"]["reaction_source"]["status"],
            "observed_pixel_reaction",
        )

    def test_unknown_opaque_raster_does_not_fall_back_to_an_occluded_native_arrow(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        with fitz.open() as overlay:
            page = overlay.new_page(width=80, height=20)
            page.draw_rect(page.rect, fill=(0, 0, 0))
            self.page.insert_image(
                fitz.Rect(175, 135, 255, 155),
                stream=page.get_pixmap(alpha=False).tobytes("png"),
            )
        self.assertEqual(self.select()[0], [])

    def test_scanned_right_arrow_proves_original_terminal(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.rasterize_route()
        self.assert_product("S2")

    def test_scanned_left_arrow_does_not_choose_rightmost(self):
        self.pair()
        self.arrow((250, 145), (180, 145))
        self.rasterize_route()
        self.assert_product("S1")

    def test_scanned_up_arrow_does_not_choose_last(self):
        self.molecule("S1", 100, 95)
        self.molecule("S2", 100, 310)
        self.arrow((142, 285), (142, 210))
        self.rasterize_route()
        self.assert_product("S1")

    def test_short_wide_head_is_not_mistaken_for_the_shaft_width(self):
        self.molecule("S1", 100, 95)
        self.molecule("S2", 100, 230)
        self.page.draw_line((142, 190), (142, 215))
        self.page.draw_polyline([(137, 207), (142, 215), (147, 207)])
        self.rasterize_route()
        self.assert_product("S2")

    def test_scanned_diagonal_arrow_is_not_horizontal_order(self):
        self.molecule("S1", 70, 95)
        self.molecule("S2", 280, 305)
        self.arrow((180, 205), (250, 275))
        self.rasterize_route()
        self.assert_product("S2")

    def test_scanned_multi_step_preserves_every_source_candidate(self):
        self.pair()
        self.molecule("S3", 490, 100)
        self.arrow((180, 145), (250, 145))
        self.arrow((390, 145), (460, 145))
        self.rasterize_route()
        self.assert_product("S3")

    def test_scanned_disconnected_candidate_is_not_removed(self):
        self.pair()
        self.molecule("S3", 80, 320)
        self.arrow((180, 145), (250, 145))
        self.rasterize_route()
        self.assertEqual(self.select()[0], [])

    def test_scanned_bidirectional_arrow_does_not_have_a_terminal(self):
        self.pair()
        self.arrow((180, 145), (250, 145), opposite_head=True)
        self.rasterize_route()
        self.assertEqual(self.select()[0], [])

    def test_scanned_two_terminal_routes_stay_unassigned(self):
        self.pair()
        self.molecule("S3", 70, 320)
        self.molecule("S4", 280, 320)
        self.arrow((180, 145), (250, 145))
        self.arrow((180, 365), (250, 365))
        self.rasterize_route()
        self.assertEqual(self.select()[0], [])

    def test_scanned_unknown_long_ink_cannot_disappear_for_uniqueness(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.page.draw_line((180, 330), (250, 330))
        self.rasterize_route()
        self.assertEqual(self.select()[0], [])

    def test_scanned_competing_branch_cannot_be_trimmed_from_an_arrow(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.page.draw_line((210, 145), (210, 159))
        self.rasterize_route()
        self.assertEqual(self.select()[0], [])

    def test_scanned_missing_head_does_not_rank_source_positions(self):
        self.pair()
        self.page.draw_line((180, 145), (250, 145))
        self.rasterize_route()
        self.assertEqual(self.select()[0], [])

    def test_scanned_connector_condition_is_not_removed(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.page.insert_text((257, 149), "N", fontsize=12)
        self.rasterize_route()
        self.assertEqual(self.select()[0], [])

    def test_scanned_edge_grazing_endpoint_is_not_treated_as_exact(self):
        self.pair()
        self.arrow((180, 103), (250, 103))
        self.rasterize_route()
        self.assertEqual(self.select()[0], [])

    def test_scanned_molecule_internal_arrow_is_not_a_reaction(self):
        self.pair()
        self.arrow((90, 130), (140, 145))
        self.rasterize_route()
        self.assertEqual(self.select()[0], [])

    def test_complete_source_and_detail_pixels_are_replayed_without_ocr(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.rasterize_route()
        binding = self.assert_product("S2")
        packet = binding["original_heading_structure_evidence"]["reaction_source"]
        self.assertEqual(packet["version"], 3)
        self.assertEqual(packet["status"], "observed_pixel_reaction")
        self.assertEqual(packet["pages"][0]["kind"], "pixels")
        self.assertEqual(original_heading_source_errors(self.document, [binding]), [])
        self.page.draw_line((210, 145), (210, 159))
        self.assertTrue(original_heading_source_errors(self.document, [binding]))

    def test_missing_or_forged_resolution_cannot_supply_saved_authority(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.rasterize_route()
        binding = self.assert_product("S2")
        changed = copy.deepcopy(binding)
        packet = changed["original_heading_structure_evidence"]["reaction_source"]
        packet["pages"][0]["details"][0]["readings"].pop()
        packet["identity"] = proof_id(
            {k: v for k, v in packet.items() if k != "identity"}
        )
        self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])
        changed = copy.deepcopy(binding)
        packet = changed["original_heading_structure_evidence"]["reaction_source"]
        packet["pages"][0]["source"]["reading"]["pixel_sha256"] = "0" * 64
        packet["identity"] = proof_id(
            {k: v for k, v in packet.items() if k != "identity"}
        )
        # A self-consistent mask/digest is still not the caller-owned PDF.
        self.assertTrue(original_heading_source_errors(self.document, [changed]))

    def test_normal_worker_and_checkpoint_keep_the_scanned_reactant_unassigned(self):
        assert_worker_checkpoint(self)

    def test_shared_web_and_source_consumers_require_actual_original_pixels(self):
        def forge(packet):
            reading = packet["pages"][0]["source"]["reading"]
            reading["pixel_sha256"] = "0" * 64
            reading["source_window"]["source_pixel_sha256"] = "0" * 64

        assert_web_original(self, mutate_source=forge)


if __name__ == "__main__":
    unittest.main()
