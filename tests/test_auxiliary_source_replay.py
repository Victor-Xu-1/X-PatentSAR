"""Actual original/source replay, not a second inference or saved admission flag."""

import copy
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from patent_sar_extractor.core.activity_auxiliary_replay import (
    auxiliary_columns,
    original_activity_source_errors,
)
from patent_sar_extractor.core.cell_raster import render_cell_raster
from patent_sar_extractor.core.table_cells import observe_original_cell
from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from patent_sar_extractor.core.text_ocr.cell_proof import (
    replay_auxiliary_cell,
)
from patent_sar_extractor.core.text_ocr.source_inventory import replay_auxiliary_source
from tests import test_auxiliary_cell_evidence as cell_fixture


class AuxiliarySourceReplayTests(unittest.TestCase):
    def setUp(self):
        fixture = cell_fixture.AuxiliaryCellEvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.page, self.document = fixture.page, fixture.document
        self.images, self.primaries = fixture.images, fixture.primaries
        pair = refine_text_pair(
            fixture.images, fixture.primaries, cell_fixture.ControlledAuxiliary()
        )
        self.assertIsNotNone(pair)
        self.payload = {
            "header_observations": {
                "controlled": {
                    "page_no": 1,
                    "observations": [{"columns": [pair[0]]}, {"columns": [pair[1]]}],
                }
            }
        }

    def test_primary_only_readers_do_not_open_any_original_or_model(self):
        reader = lambda: self.fail("No auxiliary source exists")
        self.assertEqual(original_activity_source_errors({}, open_original=reader), [])

    def test_missing_actual_original_is_not_accepted(self):
        self.assertRegex(
            original_activity_source_errors(self.payload)[0], "Original PDF is required"
        )

    def test_actual_pixels_replay_without_inference_or_sdk(self):
        with (
            patch(
                "patent_sar_extractor.core.text_ocr.configuration.get_auxiliary_text_runtime",
                side_effect=AssertionError("read side inference"),
            ),
            patch(
                "patent_sar_extractor.core.activity_auxiliary_replay.replay_auxiliary_source",
                wraps=replay_auxiliary_source,
            ) as replay,
        ):
            self.assertEqual(
                original_activity_source_errors(
                    self.payload, open_original=lambda: nullcontext(self.document)
                ),
                [],
            )
            self.assertEqual(
                replay.call_count, 1
            )  # Both DPI columns own one paired proof.

    def test_changed_complete_original_returns_false_not_an_uncaught_exception(self):
        reading = self.payload["header_observations"]["controlled"]["observations"][0][
            "columns"
        ][0]
        self.assertTrue(replay_auxiliary_cell(reading, self.page))
        self.page.insert_text((28, 76), "changed original", fontsize=6)
        self.assertFalse(replay_auxiliary_cell(reading, self.page))

    def test_invalid_reading_or_unavailable_page_never_raises_or_admits(self):
        reading = self.payload["header_observations"]["controlled"]["observations"][0][
            "columns"
        ][0]
        for changed in (None, [], "observed", {}):
            with self.subTest(changed=changed):
                self.assertFalse(replay_auxiliary_cell(changed, self.page))
        self.assertFalse(replay_auxiliary_cell(reading, None))

    def test_relabelled_page_and_changed_actual_ink_are_rejected(self):
        missing = copy.deepcopy(self.payload)
        missing["header_observations"]["controlled"]["page_no"] = True
        with self.assertRaisesRegex(ValueError, "page ownership"):
            original_activity_source_errors(missing)
        missing["header_observations"]["controlled"]["page_no"] = 2
        self.assertTrue(
            original_activity_source_errors(
                missing, open_original=lambda: nullcontext(self.document)
            )
        )
        self.page.insert_text((28, 76), "pM", fontsize=6)
        self.assertTrue(
            original_activity_source_errors(
                self.payload, open_original=lambda: nullcontext(self.document)
            )
        )

    def test_success_flags_do_not_admit_malformed_or_stripped_auxiliary(self):
        bad = copy.deepcopy(self.payload)
        column = bad["header_observations"]["controlled"]["observations"][0]["columns"][
            0
        ]
        del column["auxiliary_text"]
        with self.assertRaisesRegex(ValueError, "Unproved"):
            original_activity_source_errors(bad)

    def second_locator(self, *, changed_text=False):
        # A genuine second physical occurrence, not moved saved coordinates.
        # 72pt is an exact device translation at BOTH existing resolutions.
        self.page.insert_text((25, 117), "HTRF", fontsize=9)
        self.page.insert_text((25, 137), "EC50", fontsize=9)
        bounds = [15, 97, 140, 152]
        images = tuple(
            render_cell_raster(self.page, bounds, d, purpose="text").image
            for d in (400, 600)
        )
        primaries = tuple(
            observe_original_cell(
                self.page, bounds, "header", d, cell_fixture.primary, lambda t, _k: t
            ).evidence(d, bounds)
            for d in (400, 600)
        )
        pair = refine_text_pair(
            images,
            primaries,
            cell_fixture.ControlledAuxiliary(
                ("Noise", "EC50") if changed_text else ("HTRF", "EC50")
            ),
        )
        self.assertIsNotNone(pair)
        return {
            "page_no": 1,
            "observations": [{"columns": [pair[0]]}, {"columns": [pair[1]]}],
        }

    def test_cached_native_rows_are_not_charged_again_per_physical_occurrence(self):
        self.payload["header_observations"]["second"] = self.second_locator()
        with patch("patent_sar_extractor.core.text_ocr.source_inventory._MAX_ROWS", 4):
            self.assertEqual(len(list(auxiliary_columns(self.payload))), 2)
            self.assertEqual(
                original_activity_source_errors(
                    self.payload, open_original=lambda: nullcontext(self.document)
                ),
                [],
            )

    def test_one_cached_request_identity_cannot_claim_conflicting_outputs(self):
        self.payload["header_observations"]["second"] = self.second_locator(
            changed_text=True
        )
        with self.assertRaisesRegex(ValueError, "conflicting outputs"):
            list(auxiliary_columns(self.payload))
