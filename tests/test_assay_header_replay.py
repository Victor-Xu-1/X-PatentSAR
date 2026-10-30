"""Paired physical headers keep raw typography while sharing one strict identity."""

import copy
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from tests.test_header_physical_lines import scanned_headers


class AssayHeaderReplayTests(unittest.TestCase):
    def test_saved_detector_fragment_uses_the_same_closed_assay_comparison(self):
        document, page, region, _headers = scanned_headers()
        with (
            document,
            patch(
                "patent_sar_extractor.core.text_ocr.configuration.get_auxiliary_text_runtime",
                return_value=None,
            ),
        ):
            source = grid_schema(
                context_from_text("Table 58. Binding activity"),
                [["No.", "Noise", "Noise", "Noise"]],
            )
            proof = refine_scanned_header(page, region, source).header_resolution
        self.assertTrue(valid_header_proof(proof))
        for fragment, expected in (
            ("NanoBi'T", True),
            ("NanoBiT7", False),
            ("Nano'Bi'T", False),
            ("Target: NanoBi'T", False),
        ):
            with self.subTest(fragment=fragment):
                changed = copy.deepcopy(proof)
                column = changed["observations"][0]["columns"][2]
                detected = next(
                    part
                    for part in column["detection_parts"]
                    if part["text"] == "NanoBiT"
                )
                for part in column["detection_parts"]:
                    part["confidence"] = 0.2
                detected["text"] = fragment
                detected["confidence"] = 0.999
                self.assertEqual(valid_header_proof(changed), expected)
                self.assertEqual(detected["text"], fragment)

    def test_complete_saved_pair_accepts_only_closed_assay_typography_not_scientific_changes(
        self,
    ):
        document, page, region, _headers = scanned_headers()
        with document:
            source = grid_schema(
                context_from_text("Table 58. Binding activity"),
                [["No.", "Noise", "Noise", "Noise"]],
            )
            proof = refine_scanned_header(page, region, source).header_resolution
        self.assertTrue(valid_header_proof(proof))
        for text, accepted in (
            ("NanoBi'T", True),
            ("NanoBRET", False),
            ("Nano'Bi'T", False),
            ("HiBiT", False),
        ):
            with self.subTest(text=text):
                changed = copy.deepcopy(proof)
                observation = changed["observations"][1]
                column = observation["columns"][2]
                part = column["parts"][1]
                part["text"] = text
                column["physical_header_lines"]["row_readings"][1][0]["text"] = text
                column["raw_text"] = column["text"] = "\n".join(
                    p["text"] for p in column["parts"]
                )
                observation["matrix"][-1][2] = column["raw_text"]
                with patch(
                    "patent_sar_extractor.core.text_ocr.configuration.get_auxiliary_text_runtime",
                    side_effect=AssertionError(
                        "Pure saved header replay must not infer"
                    ),
                ):
                    self.assertEqual(valid_header_proof(changed), accepted)
                self.assertEqual(part["text"], text)
        self.assertNotIn("NanoBi'T", repr(proof))
