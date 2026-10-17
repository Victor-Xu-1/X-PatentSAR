"""Actual bounded source-window replay, without renderer/model substitution."""

import unittest

from patent_sar_extractor.core.ruled_continuation_context import (
    qualified_running_window,
)
from patent_sar_extractor.core.source_geometry import SourceLayout, SourceTokens
from patent_sar_extractor.core.source_window_chunks import observe_source_window

WINDOW = [0, 0, 520, 80]
XS, PAIRS = [40, 175, 380], ((0, 1),)


def observation(text="", *, x=220, confidence=0.99):
    words = (
        []
        if not text
        else [
            {
                "text": text,
                "x": x + 30,
                "y": 26,
                "bbox": [x, 20, x + 60, 32],
                "confidence": confidence,
                "source": "raster",
                "geometry_space": "rendered",
            }
        ]
    )
    tokens = SourceTokens(
        words, SourceLayout((), (0, 0, 520, 720)), scan_bounds=(0, 0, 520, 720)
    )
    return observe_source_window(tokens, WINDOW)


class RuledContinuationContextTests(unittest.TestCase):
    def check_context(self, **options):
        return qualified_running_window(observation(**options), WINDOW, XS, PAIRS)

    def test_complete_empty_observation_is_distinct_from_a_missing_prefix(self):
        self.assertTrue(self.check_context())
        with self.assertRaises(ValueError):
            qualified_running_window([], WINDOW, XS, PAIRS)

    def test_original_running_document_identifier_can_continue(self):
        self.assertTrue(self.check_context(text="WO2026000011"))

    def test_a_weak_running_identifier_cannot_supply_context_proof(self):
        self.assertFalse(self.check_context(text="WO2026000011", confidence=0.4))

    def test_unknown_experimental_prose_is_not_a_running_header(self):
        self.assertFalse(self.check_context(text="Different assay conditions"))

    def test_an_unowned_id_column_number_is_not_excused_as_a_page_number(self):
        self.assertFalse(self.check_context(text="37", x=60))

    def test_zero_height_is_an_actual_empty_frame_not_fabricated_source(self):
        self.assertTrue(qualified_running_window([], [0, 0, 520, 0], XS, PAIRS))
        self.assertFalse(
            qualified_running_window(observation(), [0, 0, 520, 0], XS, PAIRS)
        )
