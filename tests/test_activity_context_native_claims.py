"""A complete native source, not OCR agreement, owns explicit context claims."""

import unittest

import fitz

from patent_sar_extractor.core.activity_header_sources import (
    capture_header_sources,
    header_source_conflicts,
    select_header_context,
)
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.source_geometry import (
    SourceLayout,
    SourceTokens,
    source_layout,
)
from tests.test_activity_context_windows import draw_grid


class NativeContextClaimTests(unittest.TestCase):
    def prepare(self, *, mixed=False):
        document = fitz.open()
        self.addCleanup(document.close)
        page = document.new_page(width=500, height=600)
        page.insert_text(
            (40, 70), "Table 7. Comparison of compound activity", fontsize=9
        )
        draw_grid(page, 300, [["No.", "IC50 (nM)"], ["1", "1"]])
        native = source_layout(page)
        if mixed:
            # Controlled partial-native ownership, not original-pixel evidence.
            native = SourceLayout(native.native, (0, 80, 500, 250))
        tokens = SourceTokens(native.native, native, native.raster_bounds)
        region = {"xs": [40, 155, 335], "ys": [300, 330, 360]}
        snapshot = capture_header_sources(page, region, 1, tokens)
        return snapshot, [40, 300, 335, 330]

    def fresh(self, caption):
        return grid_schema(context_from_text(caption), [["No.", "IC50 (nM)"]])

    def test_a_complete_native_window_cannot_acquire_unprinted_conditions_by_ocr_vote(
        self,
    ):
        snapshot, band = self.prepare()
        self.assertEqual(snapshot["prefix"]["origin"], "native")
        fresh = self.fresh(
            "Table 7. Comparison of compound activity\nAssay: invented; Duration: 24 h"
        )
        flags = header_source_conflicts(snapshot, band, (), "", fresh)
        self.assertTrue(flags[1])
        self.assertIsNone(select_header_context(snapshot, band, fresh.context))

    def test_equivalent_scientific_context_retains_the_actual_native_wording(self):
        snapshot, band = self.prepare()
        fresh = self.fresh("Table 7. Comparison of conpound activity")
        self.assertFalse(header_source_conflicts(snapshot, band, (), "", fresh)[1])
        selected = select_header_context(snapshot, band, fresh.context)
        self.assertEqual(
            selected.raw_caption, "Table 7. Comparison of compound activity"
        )

    def test_native_hints_do_not_prove_absence_inside_a_mixed_raster_window(self):
        snapshot, band = self.prepare(mixed=True)
        self.assertEqual(snapshot["prefix"]["origin"], "raster")
        self.assertEqual(snapshot["native_prefix"]["origin"], "native")
        fresh = self.fresh(
            "Table 7. Comparison of compound activity\nAssay: newly observed"
        )
        self.assertFalse(header_source_conflicts(snapshot, band, (), "", fresh)[1])
