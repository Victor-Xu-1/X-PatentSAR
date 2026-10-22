"""Complete original corridors, not shaft-length distance or position ranking."""

import unittest

from raster_reaction_support import RasterReactionFixture

from patent_sar_extractor.core.reaction_connections import visible_endpoint


class ReactionConnectionScopeTests(RasterReactionFixture, unittest.TestCase):
    def test_native_long_white_gap_uses_complete_original_corridor(self):
        self.molecule("S1", 50, 100)
        self.molecule("S2", 400, 100)
        self.arrow((200, 145), (260, 145))
        self.assert_product("S2")

    def test_native_long_gap_reverse_does_not_choose_far_right(self):
        self.molecule("S1", 50, 100)
        self.molecule("S2", 400, 100)
        self.arrow((260, 145), (200, 145))
        self.assert_product("S1")

    def test_short_scanned_arrow_and_long_clear_gaps_keep_error_bounds(self):
        self.pair()
        self.arrow((208, 145), (233, 145))
        self.rasterize_route()
        self.assert_product("S2")

    def test_nominal_ray_cannot_hide_a_rival_inside_its_uncertainty(self):
        diagrams = [
            {"structure_id": "TARGET", "bbox": [400, 100, 485, 190]},
            {"structure_id": "RIVAL", "bbox": [350, 165, 435, 255]},
        ]
        with self.assertRaises(ValueError):
            visible_endpoint(
                [250, 145],
                [1, 0],
                diagrams,
                60,
                error=3,
                source_bounds=[0, 50, 660, 590],
            )


if __name__ == "__main__":
    unittest.main()
