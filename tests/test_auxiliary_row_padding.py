"""A weak SDK observation may retry blank padding, never weaken source quality."""

import copy
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from patent_sar_extractor.core.text_ocr.cell_proof import (
    replay_auxiliary_cell,
    valid_auxiliary_cell,
)
from patent_sar_extractor.core.text_ocr.process import TextOCRCancelled
from patent_sar_extractor.core.text_ocr.source_inventory import auxiliary_source_cells
from tests import test_auxiliary_cell_evidence as fixture


class PaddingAuxiliary(fixture.ControlledAuxiliary):
    def __init__(self, *, weak_second=False):
        super().__init__(("HTRF", "HTRF", "EC50", "EC50"))
        self.weak_second = weak_second

    def observe(self, image):
        observed = super().observe(image)
        observed["confidence"] = 0.975 if self.weak_second or self.calls % 2 else 0.999
        return observed


class AuxiliaryRowPaddingTests(unittest.TestCase):
    setUp = fixture.AuxiliaryCellEvidenceTests.setUp

    def test_one_compact_retry_keeps_weak_raw_observation_and_original_replay(self):
        reader = PaddingAuxiliary()
        pair = refine_text_pair(self.images, self.primaries, reader)
        self.assertIsNotNone(pair)
        self.assertEqual(reader.calls, 8)
        for reading in pair:
            self.assertEqual(reading["raw_text"], "HTRF\nEC50")
            self.assertTrue(replay_auxiliary_cell(reading, self.page))
            for view in reading["auxiliary_text"]["views"]:
                for row in view["requests"]:
                    self.assertEqual(
                        [r["confidence"] for r in row["observations"]], [0.975, 0.999]
                    )

    def test_two_weak_observations_stay_rejected_with_both_retained(self):
        reader, evidence = PaddingAuxiliary(weak_second=True), []
        self.assertIsNone(
            refine_text_pair(
                self.images, self.primaries, reader, evidence_sink=evidence
            )
        )
        self.assertEqual(reader.calls, 2)
        self.assertEqual(len(evidence[0]["views"][0]["requests"][0]["observations"]), 2)

    def test_qualified_first_read_never_requests_padding_vote(self):
        reader = fixture.ControlledAuxiliary()
        pair = refine_text_pair(self.images, self.primaries, reader)
        self.assertEqual(reader.calls, 4)
        self.assertTrue(
            all(
                len(row["observations"]) == 1
                for view in pair[0]["auxiliary_text"]["views"]
                for row in view["requests"]
            )
        )

    def test_malformed_reply_aborts_instead_of_triggering_quality_retry(self):
        reader, evidence = PaddingAuxiliary(), []
        observe = reader.observe

        def malformed(image):
            reply = observe(image)
            reply["pixel_sha256"] = "c" * 64
            return reply

        reader.observe = malformed
        self.assertIsNone(
            refine_text_pair(
                self.images, self.primaries, reader, evidence_sink=evidence
            )
        )
        self.assertEqual(reader.calls, 1)
        self.assertEqual(len(evidence[0]["views"][0]["requests"][0]["observations"]), 1)

    def test_retry_cancellation_propagates_and_all_requests_spend_budget(self):
        reader = PaddingAuxiliary()
        observe = reader.observe

        def cancelled(image):
            if reader.calls:
                raise TextOCRCancelled("controlled padding cancellation")
            return observe(image)

        reader.observe = cancelled
        with self.assertRaises(TextOCRCancelled):
            refine_text_pair(self.images, self.primaries, reader)
        reader, evidence = PaddingAuxiliary(), []
        with patch("patent_sar_extractor.core.text_ocr.source_inventory._MAX_ROWS", 3):
            self.assertIsNone(
                refine_text_pair(
                    self.images, self.primaries, reader, evidence_sink=evidence
                )
            )
        self.assertEqual(reader.calls, 3)
        rows = evidence[0]["views"][0]["requests"]
        self.assertEqual([len(r["observations"]) for r in rows], [2, 1])

    def test_removed_weak_reply_extra_retry_and_changed_padding_refuse(self):
        baseline = refine_text_pair(self.images, self.primaries, PaddingAuxiliary())
        for mutation in (
            "missing_first",
            "extra",
            "first_strong",
            "weak_last",
            "border",
            "crop",
            "shape",
            "source",
            "alternate",
            "model",
        ):
            with self.subTest(mutation=mutation):
                reading = copy.deepcopy(baseline[0])
                row = reading["auxiliary_text"]["views"][0]["requests"][0]
                if mutation == "missing_first":
                    row["observations"].pop(0)
                elif mutation == "extra":
                    row["observations"].append(copy.deepcopy(row["observations"][-1]))
                elif mutation == "first_strong":
                    row["observations"][0]["confidence"] = 0.999
                elif mutation == "weak_last":
                    row["observations"][-1]["confidence"] = 0.975
                elif mutation == "border":
                    row["border_pixels"] += 1
                elif mutation == "crop":
                    row["ink_crop_pixels"][2] -= 1
                elif mutation == "shape":
                    row["source_shape"][0] += 1
                elif mutation == "source":
                    row["source_pixel_sha256"] = "f" * 64
                elif mutation == "alternate":
                    row["observations"][-1]["pixel_sha256"] = "f" * 64
                else:
                    row["observations"][0]["model_fingerprint"] = "f" * 64
                self.assertFalse(
                    valid_auxiliary_cell(reading, 400)
                    and replay_auxiliary_cell(reading, self.page)
                )

    def test_weak_replies_are_included_in_global_inventory_conflict_and_bound(self):
        baseline = refine_text_pair(self.images, self.primaries, PaddingAuxiliary())
        self.assertEqual(len(list(auxiliary_source_cells([(1, baseline[0])]))), 1)
        with (
            patch("patent_sar_extractor.core.text_ocr.source_inventory._MAX_ROWS", 7),
            self.assertRaises(ValueError),
        ):
            list(auxiliary_source_cells([(1, baseline[0])]))
        changed = copy.deepcopy(baseline[0])
        changed["auxiliary_text"]["views"][0]["requests"][0]["observations"][0][
            "text"
        ] = "other"
        self.assertTrue(valid_auxiliary_cell(changed, 400))
        with self.assertRaisesRegex(ValueError, "conflicting outputs"):
            list(auxiliary_source_cells([(1, baseline[0]), (2, changed)]))
