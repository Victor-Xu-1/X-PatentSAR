"""Complete paired white rectangles; not missing OCR, ruling masks or zero values."""

import copy
import unittest

import fitz

from patent_sar_extractor.core.cell_empty_proof import (
    EMPTY_REGION_METHOD,
    observe_empty_grid_cell,
    observe_empty_text_region,
    replay_empty_source,
    valid_empty_source,
    valid_empty_text_region,
)


class EmptyTextRegionTests(unittest.TestCase):
    def source(self):
        document = fitz.open()
        self.addCleanup(document.close)
        page = document.new_page(width=220, height=180)
        page.insert_text((10, 20), "Outside the owned rectangle", fontsize=8)
        return page, [40, 40, 140, 90]

    def test_entire_unruled_rectangle_can_prove_only_original_absence(self):
        page, bounds = self.source()
        proof = observe_empty_text_region(page, bounds)
        self.assertIsNotNone(proof)
        self.assertEqual(proof["method"], EMPTY_REGION_METHOD)
        self.assertEqual(proof["text"], "")
        self.assertTrue(valid_empty_source(proof))
        self.assertTrue(replay_empty_source(page, proof))
        self.assertIsNone(
            observe_empty_grid_cell(page, bounds),
            "Existing closed-grid metadata policy is unchanged",
        )

    def test_even_faint_edge_ink_prevents_unruled_absence(self):
        page, bounds = self.source()
        page.draw_rect(
            fitz.Rect(40.2, 40.2, 40.9, 40.9), color=None, fill=(0.95, 0.95, 0.95)
        )
        self.assertIsNone(observe_empty_text_region(page, bounds))

    def test_saved_white_pixels_do_not_excuse_changed_original_source(self):
        page, bounds = self.source()
        proof = observe_empty_text_region(page, bounds)
        page.draw_rect(fitz.Rect(75, 60, 76, 61), color=None, fill=(0, 0, 0))
        self.assertTrue(valid_empty_text_region(proof))
        with self.assertRaises(ValueError):
            replay_empty_source(page, proof)

    def test_partial_moved_dark_only_or_malformed_packets_cannot_prove_absence(self):
        page, bounds = self.source()
        original = observe_empty_text_region(page, bounds)
        for mutate in (
            lambda proof: proof.update(method="unknown_blank"),
            lambda proof: proof.update(text="0"),
            lambda proof: proof["bbox"].__setitem__(0, 41),
            lambda proof: proof["source_pixels"]["readings"].pop(),
            lambda proof: proof["source_pixels"]["readings"].reverse(),
            lambda proof: proof["source_pixels"]["readings"][0].pop("ink_mode"),
            lambda proof: proof["source_pixels"]["readings"][0]["source_window"].update(
                purpose="text"
            ),
            lambda proof: proof["page_size"].__setitem__(0, True),
        ):
            changed = copy.deepcopy(original)
            mutate(changed)
            self.assertFalse(valid_empty_text_region(changed))

    def test_oversized_source_refuses_before_allocating_the_render(self):
        with fitz.open() as document:
            page = document.new_page(width=10000, height=10000)
            self.assertIsNone(observe_empty_text_region(page, [0, 0, 10000, 10000]))
