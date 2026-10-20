"""Blank count metadata is original absence, never a guessed number or zero."""

import copy
import unittest
from contextlib import nullcontext

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_metadata import metadata_reading_status
from patent_sar_extractor.core.activity_result_references import _observed
from patent_sar_extractor.core.cell_empty_proof import (
    observe_empty_grid_cell,
    replay_empty_grid_cell,
    valid_empty_grid_cell,
)
from patent_sar_extractor.core.source_cell_pixels import original_grid_cell_is_empty


class EmptyGridSourceTests(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        self.page = self.document.new_page(width=200, height=140)
        self.bounds = [30, 30, 130, 70]
        self.page.draw_rect(fitz.Rect(self.bounds))

    def test_empty_ruled_source_is_missing_metadata_not_an_activity(self):
        reading = observe_empty_grid_cell(self.page, self.bounds)
        self.assertIsNotNone(reading)
        self.assertTrue(valid_empty_grid_cell(reading))
        self.assertTrue(replay_empty_grid_cell(self.page, reading))
        cell = {
            "value": "",
            "raw_header": "n",
            "bbox": self.bounds,
            "observations": [reading],
        }
        self.assertEqual(metadata_reading_status(cell), "missing")
        self.assertFalse(_observed(cell))
        payload = {"rows": [{"activity_sources": [{"page_no": 1, "cells": [cell]}]}]}
        self.assertEqual(
            original_activity_source_errors(
                payload, open_original=lambda: nullcontext(self.document)
            ),
            [],
        )
        self.assertTrue(original_activity_source_errors(payload))

    def test_faint_original_count_cannot_disappear_under_a_dark_ink_threshold(self):
        self.page.insert_text((60, 55), "3", fontsize=12, color=(0.85, 0.85, 0.85))
        self.assertIsNone(observe_empty_grid_cell(self.page, self.bounds))
        self.assertFalse(original_grid_cell_is_empty(self.page, self.bounds))

    def test_changed_actual_source_and_forged_geometry_refuse(self):
        reading = observe_empty_grid_cell(self.page, self.bounds)
        wrong = copy.deepcopy(reading)
        wrong["bbox"][0] += 10
        self.assertFalse(valid_empty_grid_cell(wrong))
        self.page.insert_text((60, 55), "3", fontsize=12)
        with self.assertRaisesRegex(ValueError, "original|source|Original"):
            replay_empty_grid_cell(self.page, reading)

    def test_old_dark_mask_or_historical_inset_cannot_prove_current_absence(self):
        reading = observe_empty_grid_cell(self.page, self.bounds)
        for field in ("ink_mode", "source_window"):
            bad = copy.deepcopy(reading)
            del bad["source_pixels"]["readings"][0][field]
            self.assertFalse(valid_empty_grid_cell(bad))
        bad = copy.deepcopy(reading)
        bad["source_pixels"]["readings"][0]["ink_mode"] = True
        self.assertFalse(valid_empty_grid_cell(bad))
