"""One shared header adapter, constrained to unresolved original columns."""

import copy
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.activity_header_columns import HeaderColumns
from patent_sar_extractor.core.activity_header_pair import observe_header_pair
from tests import test_auxiliary_cell_evidence as cell_fixture


class AuxiliaryHeaderPairTests(unittest.TestCase):
    def setUp(self):
        fixture = cell_fixture.AuxiliaryCellEvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.region = {"xs": [15, 140], "ys": [25, 80, 100]}
        self.columns = [
            {
                **p,
                "native_text": "",
                "physical_column": 0,
                "crosses_boundary": False,
                "detector_conflict": False,
            }
            for p in fixture.primaries
        ]

    def observe(self, reader, *, qualified=False):
        views = [
            HeaderColumns([[p["raw_text"]]], (p,), (qualified,)) for p in self.columns
        ]
        with patch(
            "patent_sar_extractor.core.activity_header_pair.get_auxiliary_text_runtime",
            return_value=reader,
        ) as acquire:
            pair = observe_header_pair(
                self.fixture.page, self.region, 1, (), lambda *a: views.pop(0)
            )
        return pair, acquire

    def test_qualified_primary_and_unconfigured_auxiliary_keep_existing_path(self):
        pair, acquire = self.observe(cell_fixture.ControlledAuxiliary(), qualified=True)
        acquire.assert_not_called()
        self.assertNotIn("auxiliary_text", pair[0].columns[0])
        pair, _ = self.observe(None)
        self.assertEqual(pair[0].columns[0], self.columns[0])

    def test_bounded_auxiliary_keeps_original_identity_and_coordinates(self):
        before = copy.deepcopy(self.columns)
        pair, _ = self.observe(cell_fixture.ControlledAuxiliary())
        self.assertEqual(self.columns, before)
        self.assertEqual(pair[0].matrix, [["HTRF\nEC50"]])
        self.assertEqual(pair[0].columns[0]["bbox"], before[0]["bbox"])
        self.assertEqual(pair[0].columns[0]["physical_column"], 0)
        self.assertTrue(all(v.verified == (True,) for v in pair))

    def test_known_original_conflicts_and_crossing_are_never_rescued(self):
        for field in ("detector_conflict", "crosses_boundary"):
            before = copy.deepcopy(self.columns)
            self.columns[0][field] = True
            reader = cell_fixture.ControlledAuxiliary()
            pair, _ = self.observe(reader)
            self.assertEqual(reader.calls, 0)
            self.assertFalse(pair[0].verified[0])
            self.columns = before

    def test_disagreement_retains_unresolved_primary_instead_of_voting(self):
        reader = cell_fixture.ControlledAuxiliary(("HTRF", "EC50", "HTRF", "IC50"))
        pair, _ = self.observe(reader)
        self.assertFalse(any(v.verified[0] for v in pair))
        saved = pair[0].columns[0]
        self.assertEqual(
            {k: v for k, v in saved.items() if k != "auxiliary_attempt"},
            self.columns[0],
        )
        self.assertEqual(saved["auxiliary_attempt"]["status"], "rejected")
        packet = saved["auxiliary_attempt"]["packet"]
        self.assertEqual(
            packet["views"][1]["requests"][-1]["observations"][-1]["text"], "IC50"
        )

    def test_failed_auxiliary_keeps_primary_and_partial_observations(self):
        reader = cell_fixture.ControlledAuxiliary()
        original = reader.observe

        def fail_second(image):
            if reader.calls:
                raise TimeoutError("controlled native stall")
            return original(image)

        reader.observe = fail_second
        pair, _ = self.observe(reader)
        saved = pair[0].columns[0]
        self.assertFalse(pair[0].verified[0])
        self.assertEqual(saved["raw_text"], self.columns[0]["raw_text"])
        self.assertEqual(saved["auxiliary_attempt"]["code"], "request_timeout")
        self.assertEqual(
            saved["auxiliary_attempt"]["views"][0]["requests"][0]["observations"][0][
                "text"
            ],
            "HTRF",
        )

    def test_valid_below_threshold_reply_is_rejected_not_runtime_unavailable(self):
        for score, text in ((0.98, "HTRF"), (0.999, "")):
            with self.subTest(score=score, text=text):
                reader = cell_fixture.ControlledAuxiliary()
                original = reader.observe

                def weak(image, *, original=original, score=score, text=text):
                    return {**original(image), "confidence": score, "text": text}

                reader.observe = weak
                pair, _ = self.observe(reader)
                self.assertFalse(any(v.verified[0] for v in pair))
                for view, primary in zip(pair, self.columns, strict=True):
                    saved = view.columns[0]
                    self.assertEqual(
                        {k: v for k, v in saved.items() if k != "auxiliary_attempt"},
                        primary,
                    )
                    attempt = saved["auxiliary_attempt"]
                    self.assertEqual(attempt["status"], "rejected")
                    self.assertEqual(attempt["code"], "unqualified_original_row")
                    observations = attempt["views"][0]["requests"][0]["observations"]
                    self.assertGreaterEqual(len(observations), 1)
                    self.assertLessEqual(len(observations), 3)
                    self.assertTrue(all(o["confidence"] == score for o in observations))
                    self.assertTrue(all(o["text"] == text for o in observations))
                self.assertLessEqual(reader.calls, 3)

    def test_invalid_reply_is_not_reported_as_a_quality_rejection(self):
        reader = cell_fixture.ControlledAuxiliary()
        original = reader.observe

        def invalid(image):
            return {**original(image), "pixel_sha256": "c" * 64, "confidence": 0.9}

        reader.observe = invalid
        pair, _ = self.observe(reader)
        self.assertFalse(any(v.verified[0] for v in pair))
        attempt = pair[0].columns[0]["auxiliary_attempt"]
        self.assertEqual(attempt["status"], "unavailable")
        self.assertEqual(attempt["code"], "runtime_or_source_failure")
        self.assertEqual(reader.calls, 1)
