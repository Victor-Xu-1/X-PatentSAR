"""A proved enclosing rule is its literal ink, never its whole interior area."""

import unittest

import fitz
import numpy as np

from patent_sar_extractor.core.cell_raster import retained_pixel_origin
from patent_sar_extractor.core.plot_reference_pixels import retained_pixels
from patent_sar_extractor.core.raster_reaction_pixels import (
    observe_raster_source,
    source_vectors,
)
from patent_sar_extractor.core.reaction_pixel_frame import frame_ink


class ReactionPixelFrameTests(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        self.page = self.document.new_page(width=120, height=120)
        self.page.draw_rect(fitz.Rect(10, 10, 110, 110), width=0.6)

    def packet(self, frame=None):
        frame = [10, 10, 110, 110] if frame is None else frame
        bounds = [frame[0], 20, frame[2], 100]
        return observe_raster_source(self.page, bounds, original_frame=frame)

    def test_literal_edges_do_not_create_an_interior_area_blocker(self):
        vectors, windows = source_vectors(self.packet(), [])
        self.assertEqual(windows, [])
        self.assertTrue(vectors["blockers"])
        self.assertFalse(
            any(
                box[0] < 60 < box[2] and box[1] < 60 < box[3]
                for box in vectors["blockers"]
            )
        )

    def test_unknown_mark_joining_a_rule_is_not_trimmed_out(self):
        self.page.draw_line((10, 50), (45, 50))
        with self.assertRaises(ValueError):
            source_vectors(self.packet(), [])

    def test_an_interior_fill_cannot_be_authorized_by_the_frame(self):
        self.page.draw_rect(fitz.Rect(40, 35, 80, 70), fill=(0, 0, 0))
        with self.assertRaises(ValueError):
            source_vectors(self.packet(), [])

    def test_content_clip_without_visible_rules_authorizes_no_frame_pixels(self):
        source = self.packet([11, 10, 109, 110])
        mask = retained_pixels(source["reading"], source["bounds"], 200, 8_000_000)
        origin = retained_pixel_origin(source["reading"], source["bounds"], 200)
        allowed, boxes = frame_ink(source, mask, origin, 200)
        self.assertFalse(np.any(allowed))
        self.assertEqual(boxes, [])

    def test_an_arbitrary_inner_frame_cannot_widen_the_original_window(self):
        source = self.packet()
        source["frame"] = [30, 30, 80, 80]
        with self.assertRaises(ValueError):
            source_vectors(source, [])


if __name__ == "__main__":
    unittest.main()
