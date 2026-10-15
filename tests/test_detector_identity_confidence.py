"""Qualified literal conflicts are not the same as low-confidence OCR hints."""

import unittest
from unittest.mock import Mock, patch

from test_cell_line_coverage import pixels
from test_header_physical_lines import scanned_headers

from patent_sar_extractor.core.activity_header_identity import detector_header_conflict
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.cell_caption_identity import refined_caption_conflicts
from patent_sar_extractor.core.cell_ocr_observation import observe_cell
from patent_sar_extractor.core.numbered_structure_pairs import _confirmed_observations
from patent_sar_extractor.core.page_ocr_cache import get_ocr_engine
from patent_sar_extractor.core.table_cells import _normalize


def part(text, confidence):
    return {
        "text": text,
        "confidence": confidence,
        "bbox": [[8, 8], [180, 8], [180, 42], [8, 42]],
        "coordinate_space": "cell_ink_crop_pixels",
    }


class DetectorIdentityConfidenceTests(unittest.TestCase):
    def test_malformed_confidence_is_not_a_neutral_low_confidence_observation(self):
        for score in (True, False, None, "0.99", float("nan"), float("inf"), -1, 2):
            with self.subTest(score=score):
                self.assertTrue(
                    detector_header_conflict([part("IC50 (nM)", score)], "IC50 (nM)")
                )

    def test_qualified_endpoint_only_does_not_assert_an_absent_context(self):
        self.assertFalse(
            detector_header_conflict([part("IC50 (nM)", 0.99)], "TargetX IC50 (nM)")
        )
        self.assertTrue(
            detector_header_conflict([part("IC50 (nM)", 0.99)], "TargetX IC50 (uM)")
        )

    def test_known_native_target_and_ordered_units_are_not_projected_away(self):
        from patent_sar_extractor.core.activity_header_identity import header_conflict

        self.assertTrue(header_conflict("nM", "TargetA IC50 (pM)"))
        self.assertFalse(header_conflict("nM", "TargetA IC50 (nM)"))
        self.assertTrue(
            detector_header_conflict(
                [part("TargetA IC50 (nM)", 0.99)], "TargetB IC50 (nM)"
            )
        )
        self.assertTrue(
            detector_header_conflict(
                [part("IC50 (nM) EC50 (uM)", 0.99)], "IC50 (uM) EC50 (nM)"
            )
        )

    def test_qualified_target_fragment_survives_a_weak_endpoint_word(self):
        original = [part("TargetA", 0.99), part("IC50", 0.2), part("nM", 0.99)]
        self.assertTrue(detector_header_conflict(original, "TargetB IC50 (nM)"))
        self.assertFalse(detector_header_conflict(original, "TargetA IC50 (nM)"))
        self.assertTrue(
            detector_header_conflict([part("TargetA", 0.99)], "TargetAB IC50 (nM)")
        )

    def test_qualified_identifier_fragment_survives_an_unqualified_prefix(self):
        complete = [
            {**part("Compound 42", 0.99), "method": "complete_line_recognition"}
        ]
        prefix = part("Compound", 0.2)
        prefix["bbox"] = [[8, 8], [120, 8], [120, 42], [8, 42]]
        number = part("43", 0.99)
        number["bbox"] = [[130, 8], [180, 8], [180, 42], [130, 42]]
        self.assertTrue(refined_caption_conflicts("42", complete, [prefix, number]))
        number["text"] = "42"
        self.assertFalse(refined_caption_conflicts("42", complete, [prefix, number]))

    def test_invalid_engine_score_cannot_become_a_neutral_detector_hint(self):
        for raw_score in (True, "0.99", float("nan"), float("inf"), -1, 2):
            with self.subTest(raw_score=raw_score):
                engine = Mock(
                    side_effect=[
                        (
                            (
                                [
                                    part("Compound", raw_score)["bbox"],
                                    "Compound",
                                    raw_score,
                                ],
                            ),
                            0,
                        ),
                        ([["Compound 137", 0.99]], 0),
                    ]
                )
                observed = observe_cell(pixels(), "label", 400, engine, _normalize)
                self.assertEqual(observed.value, "")
                self.assertEqual(observed.raw_text, "Compound 137")
                self.assertIs(observed.detection_parts[0]["confidence_valid"], False)
                packet = observed.evidence(400, [20, 30, 160, 45])
                packet["text"] = "137"  # A saved success claim is not original proof.
                self.assertFalse(
                    _confirmed_observations(
                        "137",
                        [{"method": "page_ocr_cell", "text": "Compound 137"}, packet],
                        caption=True,
                    )
                )

    def test_qualified_context_with_a_unit_cannot_disappear(self):
        for fragment in ("TargetA nM", "TargetA(nM)", "TargetA (nM)"):
            with self.subTest(fragment=fragment):
                self.assertTrue(
                    detector_header_conflict(
                        [part(fragment, 0.99)], "TargetB IC50 (nM)"
                    )
                )
                self.assertFalse(
                    detector_header_conflict(
                        [part(fragment, 0.99)], "TargetA IC50 (nM)"
                    )
                )


class DetectorIdentityNativeTests(unittest.TestCase):
    def test_real_bounded_header_reader_retains_unqualified_detection_and_valid_source_lines(
        self,
    ):
        engine = get_ocr_engine()[1]
        captured = []

        def unqualified_detection(image, **options):
            result, duration = engine(image, **options)
            if options.get("use_det", True):
                result = [
                    [box, "OtherTarget EC50 (uM)", 0.2]
                    for box, _text, _score in result or []
                ]
                captured.extend(result)
            return result, duration

        doc, page, region, _ = scanned_headers()
        source = grid_schema(
            context_from_text("Table 58. Binding activity"),
            [["No.", "Noise", "Noise", "Noise"]],
        )
        with (
            doc,
            patch(
                "patent_sar_extractor.core.activity_header_columns.get_ocr_engine",
                return_value=("rapidocr", unqualified_detection),
            ),
        ):
            observed = refine_scanned_header(page, region, source)
        self.assertTrue(captured)
        self.assertTrue(
            valid_header_proof(observed.header_resolution), observed.header_resolution
        )
        self.assertEqual(observed.raw_headers[1], "TR-FRET\nBRD9\nIC50\nnM")
        for reading in observed.header_resolution["observations"]:
            for column in reading["columns"]:
                self.assertTrue(
                    all(part["confidence"] == 0.2 for part in column["detection_parts"])
                )

    def test_low_confidence_whole_header_is_retained_but_not_a_valid_conflicting_claim(
        self,
    ):
        self.assertFalse(
            detector_header_conflict(
                [
                    part("WrongTarget EC50 (uM)", 0.2),
                ],
                "TargetX IC50 (nM)",
            )
        )

    def test_qualified_endpoint_and_unit_conflict_survives_other_unqualified_words(
        self,
    ):
        self.assertTrue(
            detector_header_conflict(
                [
                    part("WrongTarget", 0.2),
                    part("EC50 (pM)", 0.99),
                ],
                "TargetX IC50 (nM)",
            )
        )
        self.assertFalse(
            detector_header_conflict(
                [
                    part("WrongTarget", 0.2),
                    part("IC50 (nM)", 0.99),
                ],
                "TargetX IC50 (nM)",
            )
        )

    def test_qualified_whole_header_is_never_outvoted(self):
        self.assertTrue(
            detector_header_conflict(
                [
                    part("WrongTarget IC50 (nM)", 0.99),
                ],
                "TargetX IC50 (nM)",
            )
        )

    def test_caption_detector_hint_cannot_outvote_a_complete_literal_line(self):
        complete = [
            {**part("Compound 42", 0.99), "method": "complete_line_recognition"}
        ]
        self.assertFalse(
            refined_caption_conflicts("42", complete, [part("Compound 43", 0.2)])
        )
        self.assertTrue(
            refined_caption_conflicts("42", complete, [part("Compound 43", 0.99)])
        )
