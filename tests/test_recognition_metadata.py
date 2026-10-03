from __future__ import annotations

import unittest

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.recognition import recognition_status


class RecognitionMetadataTests(unittest.TestCase):
    def test_binding_and_manual_decisions_are_not_recognition_evidence(self):
        self.assertEqual(recognition_status({}, current=True)["status"], "not_run")
        self.assertEqual(
            recognition_status({"rdkit_valid": True}, current=True)["status"],
            "unavailable",
        )
        self.assertEqual(
            recognition_status(
                {"rdkit_valid": True, "OCSR_quality_flag": "ok"}, current=False
            )["status"],
            "unavailable",
        )

    def test_clean_record_retains_content_identity_and_uncalibrated_token_values(self):
        value = recognition_status(
            {
                "rdkit_valid": True,
                "OCSR_quality_flag": "ok",
                "model_fingerprint": "a" * 64,
                "token_confidence": {"minimum": 0.4, "mean": 0.8},
            },
            current=True,
        )
        self.assertEqual(value["status"], "valid")
        self.assertEqual(value["model_fingerprint"], "a" * 64)
        self.assertEqual(value["token_confidence"], {"minimum": 0.4, "mean": 0.8})
        self.assertNotIn("accuracy", value)

    def test_bad_quality_metadata_is_not_silently_accepted(self):
        for confidence in (
            {"minimum": float("nan"), "mean": 0.8},
            {"minimum": True, "mean": 0.8},
            {"minimum": 0.9, "mean": 0.8},
            {"minimum": 0.5, "mean": 1.2},
            {"mean": 0.8},
        ):
            with self.subTest(confidence=confidence), self.assertRaises(WebError):
                recognition_status({"token_confidence": confidence}, current=True)
        with self.assertRaises(WebError):
            recognition_status(
                {"model_fingerprint": "not a content digest"}, current=True
            )

    def test_query_and_invalid_predictions_remain_invalid(self):
        for flag in ("invalid_smiles", "markush_or_query", "suspicious_element"):
            self.assertEqual(
                recognition_status(
                    {"rdkit_valid": True, "OCSR_quality_flag": flag}, current=True
                )["status"],
                "invalid",
            )


if __name__ == "__main__":
    unittest.main()
