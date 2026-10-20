"""Paint facts are call-local, bounded, original and never reused after edits."""

import copy
import unittest
from contextlib import nullcontext
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_grid_cells import read_activity_cell
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.source_observations import source_cell_observation
from patent_sar_extractor.core.source_paint_visibility import (
    native_paint_view,
    visible_native_tokens,
)


class NativePaintViewTests(unittest.TestCase):
    def setUp(self):
        with fitz.open() as source:
            page = source.new_page(width=240, height=500)
            for index in range(12):
                page.insert_text((30, 40 + index * 30), "0.4", fontsize=10)
            self.document = fitz.open(stream=source.tobytes(), filetype="pdf")
        self.addCleanup(self.document.close)
        self.page = self.document[0]
        layout = source_layout(self.page)
        self.tokens = SourceTokens(layout.native, layout, layout.raster_bounds)
        self.bounds = [20, 25, 100, 50]

    def profile(self):
        return source_cell_observation(self.tokens, self.bounds, native=True)

    def test_many_native_cells_reuse_one_readonly_page_paint_inventory(self):
        with patch(
            "patent_sar_extractor.core.activity_grid_cells.native_paint_view",
            wraps=native_paint_view,
        ) as capture:
            observations = []
            for index in range(12):
                bounds = [20, 25 + index * 30, 100, 50 + index * 30]
                value, readings, review = read_activity_cell(
                    self.page, self.tokens, bounds, identifier=False, native=True
                )
                self.assertEqual(value, "0.4")
                self.assertFalse(review)
                observations.append({"observations": readings})
            self.assertEqual(capture.call_count, 1)
        payload = {
            "rows": [{"activity_sources": [{"page_no": 1, "cells": observations}]}]
        }
        with patch(
            "patent_sar_extractor.core.activity_auxiliary_replay.native_paint_view",
            wraps=native_paint_view,
        ) as replay:
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(self.document)
                ),
                [],
            )
            self.assertEqual(replay.call_count, 1)

    def test_wrong_document_and_inplace_stream_edits_cannot_reuse_paint_facts(self):
        view, profile = native_paint_view(self.page), self.profile()
        self.assertTrue(visible_native_tokens(self.page, profile, paint_view=view))
        with fitz.open(stream=self.document.tobytes(), filetype="pdf") as other:
            self.assertFalse(visible_native_tokens(other[0], profile, paint_view=view))
        last = self.page.get_contents()[-1]
        before = tuple(self.page.get_contents())
        self.document.update_stream(
            last,
            self.document.xref_stream(last) + b"\nq 1 1 1 rg 20 450 80 25 re f Q\n",
        )
        self.assertEqual(tuple(self.page.get_contents()), before)
        self.assertFalse(visible_native_tokens(self.page, profile, paint_view=view))

    def test_visible_covering_annotation_is_not_ignored_native_text(self):
        profile = copy.deepcopy(self.profile())
        annotation = self.page.add_rect_annot(fitz.Rect(self.bounds))
        annotation.set_colors(stroke=(1, 1, 1), fill=(1, 1, 1))
        annotation.update()
        self.assertFalse(visible_native_tokens(self.page, profile))
