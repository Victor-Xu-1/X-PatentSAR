"""Operational timeouts remain source-owned failures, never repaired values."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from patent_sar_extractor.core.text_ocr.process import (
    TextOCRCancelled,
    TextOCRPhaseTimeout,
)
from tests import test_auxiliary_cell_evidence as controlled


class AuxiliaryFailurePhaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = controlled.AuxiliaryCellEvidenceTests(
            "test_whole_original_pair_and_weak_primaries_are_preserved"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_phase_timeouts_keep_raw_primary_sources_and_distinct_diagnostics(self):
        before = copy.deepcopy(self.fixture.primaries)
        for phase in (
            "queue",
            "identity",
            "worker_ready",
            "source_frame",
            "model_prepare",
            "inference",
            None,
        ):
            error = (
                TextOCRPhaseTimeout(phase)
                if phase
                else TimeoutError("Controlled legacy timeout")
            )
            attempts = []
            reader = SimpleNamespace(observe=Mock(side_effect=error))
            with self.subTest(phase=phase):
                self.assertIsNone(
                    refine_text_pair(
                        self.fixture.images,
                        self.fixture.primaries,
                        reader,
                        evidence_sink=attempts,
                    )
                )
                self.assertEqual(attempts[0]["status"], "unavailable")
                self.assertEqual(
                    attempts[0]["code"],
                    phase + "_timeout" if phase else "request_timeout",
                )
                self.assertEqual(self.fixture.primaries, before)
                self.assertEqual(attempts[0]["views"][0]["primary"], before[0])

    def test_cancel_is_propagated_not_changed_into_an_unavailable_or_valid_read(self):
        before = copy.deepcopy(self.fixture.primaries)
        attempts = []
        reader = SimpleNamespace(
            observe=Mock(side_effect=TextOCRCancelled("Controlled cancellation"))
        )
        with self.assertRaises(TextOCRCancelled):
            refine_text_pair(
                self.fixture.images,
                self.fixture.primaries,
                reader,
                evidence_sink=attempts,
            )
        self.assertEqual(attempts, [])
        self.assertEqual(self.fixture.primaries, before)


if __name__ == "__main__":
    unittest.main()
