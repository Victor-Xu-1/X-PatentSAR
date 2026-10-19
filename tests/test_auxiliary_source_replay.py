"""Actual original/source replay, not a second inference or saved admission flag."""

import copy
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from patent_sar_extractor.core.activity_auxiliary_replay import (
    auxiliary_columns,
    original_activity_source_errors,
)
from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from patent_sar_extractor.core.text_ocr.cell_proof import (
    effective_cells,
    replay_auxiliary_cell,
)
from tests import test_auxiliary_cell_evidence as cell_fixture


class AuxiliarySourceReplayTests(unittest.TestCase):
    def setUp(self):
        fixture = cell_fixture.AuxiliaryCellEvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.page, self.document = fixture.page, fixture.document
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
                "patent_sar_extractor.core.activity_auxiliary_replay.replay_auxiliary_cell",
                wraps=replay_auxiliary_cell,
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
        proof = self.payload["header_observations"]["controlled"]
        packet = copy.deepcopy(proof["observations"][0]["columns"][0]["auxiliary_text"])
        for view in packet["views"]:
            view["primary"]["bbox"][0] += 1
            view["primary"]["bbox"][2] += 1
            if changed_text:
                view["rows"][0]["observation"]["text"] = "Noise"
        pair = effective_cells(packet)
        return {
            "page_no": 1,
            "observations": [{"columns": [pair[0]]}, {"columns": [pair[1]]}],
        }

    def test_cached_native_rows_are_not_charged_again_per_physical_occurrence(self):
        self.payload["header_observations"]["second"] = self.second_locator()
        with patch("patent_sar_extractor.core.activity_auxiliary_replay._MAX_ROWS", 4):
            self.assertEqual(len(list(auxiliary_columns(self.payload))), 2)

    def test_one_cached_request_identity_cannot_claim_conflicting_outputs(self):
        self.payload["header_observations"]["second"] = self.second_locator(
            changed_text=True
        )
        with self.assertRaisesRegex(ValueError, "conflicting outputs"):
            list(auxiliary_columns(self.payload))
