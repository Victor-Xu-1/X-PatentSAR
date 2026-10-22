"""Solid raster heads retain their full geometry without invented paint data."""

import unittest

from native_reaction_consumers import assert_web_original, assert_worker_checkpoint
from raster_reaction_support import RasterReactionFixture

from patent_sar_extractor.core.reaction_page_source import source_page_vectors


class RasterFilledReactionTests(RasterReactionFixture, unittest.TestCase):
    def assert_filled(self, identity):
        binding = self.assert_product(identity)
        evidence = binding["original_heading_structure_evidence"]
        source = evidence["reaction_source"]["pages"][0]
        regions = [
            row["bbox"]
            for row in evidence["declaration_scope"]["pages"][0]["structures"]
        ]
        vectors, _ = source_page_vectors(source, regions)
        self.assertEqual(vectors["version"], 3)
        self.assertTrue(vectors["filled_heads"])
        self.assertTrue(
            all(set(head) == {"points"} for head in vectors["filled_heads"])
        )

    def test_scanned_solid_right_head_selects_terminal(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True)
        self.rasterize_route()
        self.assert_filled("S2")

    def test_scanned_solid_left_head_does_not_select_last(self):
        self.pair()
        self.arrow((250, 145), (180, 145), filled=True)
        self.rasterize_route()
        self.assert_filled("S1")

    def test_scanned_solid_up_head_selects_upper_source(self):
        self.molecule("S1", 100, 95)
        self.molecule("S2", 100, 310)
        self.arrow((142, 285), (142, 210), filled=True)
        self.rasterize_route()
        self.assert_filled("S1")

    def test_scanned_solid_diagonal_head_keeps_full_direction(self):
        self.molecule("S1", 70, 95)
        self.molecule("S2", 280, 305)
        self.arrow((180, 205), (250, 275), filled=True)
        self.rasterize_route()
        self.assert_filled("S2")

    def test_reversible_solid_heads_do_not_become_one_way(self):
        self.pair()
        self.arrow((180, 145), (250, 145), filled=True, opposite_head=True)
        self.rasterize_route()
        self.assertEqual(self.select()[0], [])

    def test_diamond_and_blunt_polygons_are_not_simplified_to_a_head(self):
        for points in (
            [(250, 145), (243, 140), (236, 145), (243, 150)],
            [(250, 142), (250, 148), (240, 151), (240, 139)],
        ):
            with self.subTest(points=points):
                self.setUp()
                self.pair()
                self.page.draw_line((180, 145), (250, 145))
                self.page.draw_polyline(points, closePath=True, fill=(0, 0, 0))
                self.rasterize_route()
                self.assertEqual(self.select()[0], [])

    def test_normal_worker_keeps_solid_route_reactants_and_checkpoint(self):
        assert_worker_checkpoint(self, filled=True)

    def test_web_replays_solid_source_without_inventing_rgb_or_stroke_style(self):
        def forge(packet):
            reading = packet["pages"][0]["details"][0]["readings"][0]
            reading["pixel_sha256"] = "0" * 64
            reading["source_window"]["source_pixel_sha256"] = "0" * 64

        assert_web_original(self, filled=True, mutate_source=forge)


if __name__ == "__main__":
    unittest.main()
