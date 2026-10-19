"""New activity proof never retags old observations or saved QA into acceptance."""

import copy
import unittest
from unittest.mock import patch

from patent_sar_extractor import contracts
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.web.acceptance import authority, current
from tests.test_web_acceptance import complete_payloads


class AuxiliaryActivityCompatibilityTests(unittest.TestCase):
    def test_prior_activity_is_historical_even_with_saved_success(self):
        payloads = complete_payloads()
        payloads["activity"]["schema"]["version"] = (
            contracts.ACTIVITY_SCHEMA_VERSION - 1
        )
        before = copy.deepcopy(payloads)
        decision, _ = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(decision.state, "historical")
        self.assertFalse(current(payloads["activity"], "activity"))
        self.assertTrue(current(payloads["bindings"], "bindings"))
        self.assertEqual(payloads, before)
        with self.assertRaisesRegex(ValueError, "incompatible"):
            activity_evidence_errors(payloads["activity"])

    def test_current_read_only_admission_never_starts_auxiliary_recognition(self):
        payloads = complete_payloads()
        before = copy.deepcopy(payloads)
        with patch(
            "patent_sar_extractor.core.text_ocr.configuration.get_auxiliary_text_runtime",
            side_effect=AssertionError("Read side model use"),
        ):
            decision, _ = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(decision.state, "accepted", decision.errors)
        self.assertEqual(payloads, before)
