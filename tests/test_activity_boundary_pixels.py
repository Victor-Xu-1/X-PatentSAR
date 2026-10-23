"""Full raster-boundary ownership with controlled tokens and zero OCR calls."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core import page_ocr_cache
from patent_sar_extractor.core.activity_boundary_pixels import (
    original_boundary_pixels_match,
    valid_boundary_pixels,
)
from patent_sar_extractor.core.activity_boundary_sources import (
    layout_boundary_sources,
    original_context_boundaries,
)
from patent_sar_extractor.core.activity_context_geometry import context_region
from patent_sar_extractor.core.activity_grid_context import _prefix
from patent_sar_extractor.core.activity_parallel_context import (
    observe_context_boundary,
    validate_context_boundary,
)
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout


class ActivityBoundaryPixelTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(page_ocr_cache, "_OCR_ENGINE", None))
        self.engine = self.enterContext(
            patch.object(
                page_ocr_cache,
                "_build_ocr_engine",
                side_effect=AssertionError("No OCR"),
            )
        )
        self.document = self.enterContext(fitz.open())
        page = self.document.new_page(width=500, height=400)
        page.insert_text(
            (40, 40), "[ 42 ] Table 9 (continued)\nDuration: 24 h", fontsize=9
        )
        native = source_layout(page)
        self.image = page.get_pixmap(dpi=144).tobytes("png")
        raster_tokens = [
            {
                **{k: v for k, v in token.items() if k != "native_paint"},
                "source": "raster",
                "confidence": 0.99,
            }
            for token in native.native
        ]
        self.page = self.document.new_page(width=500, height=400)
        self.page.insert_image(self.page.rect, stream=self.image)
        layout = source_layout(self.page)
        self.tokens = SourceTokens(raster_tokens, layout, layout.raster_bounds)
        self.region = context_region(
            {"xs": [40, 155, 335], "ys": [120, 150, 180]}, [[40, 120, 335, 180]]
        )
        self.scope = observe_context_boundary(self.page, self.region, self.tokens)
        self.prefix = _prefix(self.tokens, self.region)
        self.bounds = [0, 0, 500, 120]

    def tearDown(self):
        self.engine.assert_not_called()

    def test_full_boundary_pixels_replay_without_a_new_recognition(self):
        self.assertEqual(self.scope["version"], 2)
        self.assertTrue(
            valid_boundary_pixels(self.scope["original_pixels"], self.bounds)
        )
        self.assertIsNotNone(
            validate_context_boundary(self.region, self.scope, self.prefix)
        )
        self.assertTrue(
            original_boundary_pixels_match(self.scope, self.bounds, self.page)
        )
        self.page.draw_rect(fitz.Rect(35, 28, 330, 67), color=None, fill=(1, 1, 1))
        self.assertFalse(
            original_boundary_pixels_match(self.scope, self.bounds, self.page)
        )

    def test_missing_or_changed_window_and_hash_cannot_supply_boundary_authority(self):
        for alteration in ("missing", "hash", "window", "purpose", "size"):
            scope = copy.deepcopy(self.scope)
            if alteration == "missing":
                scope["original_pixels"] = None
            elif alteration == "hash":
                scope["original_pixels"]["frame"]["pixel_sha256"] = "0" * 64
            elif alteration == "window":
                scope["original_pixels"]["window"]["read_bounds"][0] += 1
            elif alteration == "purpose":
                scope["original_pixels"]["window"]["purpose"] = "text"
            else:
                scope["page_size"][0] -= 1
            with self.subTest(alteration=alteration):
                self.assertFalse(
                    original_boundary_pixels_match(scope, self.bounds, self.page)
                )

    def test_borrowed_layout_cannot_drop_or_downgrade_its_complete_local_boundary(self):
        base = {
            **self.region,
            "data_start": 0,
            "header_origin": {"page_no": 1},
            "prefix": self.prefix,
            "continuation_context": self.scope,
        }
        self.assertEqual(len(list(layout_boundary_sources(base, 2))), 1)
        for alteration in ("missing", "downgrade", "pixels"):
            layout = copy.deepcopy(base)
            if alteration == "missing":
                layout.pop("continuation_context")
            elif alteration == "downgrade":
                layout["continuation_context"]["version"] = 1
                layout["continuation_context"].pop("original_pixels")
            else:
                layout["continuation_context"]["original_pixels"] = None
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                list(layout_boundary_sources(layout, 2))

    def test_oversized_raster_prefix_refuses_before_rendering_or_starting_ocr(self):
        page = self.document.new_page(width=2000, height=600)
        page.insert_image(page.rect, stream=self.image)
        layout = source_layout(page)
        tokens = SourceTokens([], layout, layout.raster_bounds)
        region = context_region(
            {"xs": [40, 400, 900], "ys": [400, 430]}, [[40, 400, 900, 430]]
        )
        with self.assertLogs(
            "patent_sar_extractor.core.activity_parallel_context", level="WARNING"
        ) as messages:
            self.assertIsNone(observe_context_boundary(page, region, tokens))
        self.assertIn("pixel budget", messages.output[0])

    def test_one_original_frame_is_replayed_once_without_dropping_local_claim_owners(
        self,
    ):
        layout = {
            **self.region,
            "data_start": 0,
            "header_origin": {"page_no": 1},
            "prefix": self.prefix,
            "parallel_context": self.scope,
            "continuation_context": self.scope,
        }
        self.assertEqual(len(list(layout_boundary_sources(layout, 2))), 2)
        payload = {"coverage": {"regions": [{"page_no": 2, "layout": layout}]}}
        self.assertEqual(len(list(original_context_boundaries(payload))), 1)


if __name__ == "__main__":
    unittest.main()
