"""Overlapping role locators never invent or erase original identifier claims."""

import json
import unittest

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.cell_caption_identity import refined_caption_conflicts
from patent_sar_extractor.core.compound_caption import prefixed_label


def part(text, x0=0, x1=150, score=0.98, method=None):
    return {
        "text": text,
        "confidence": score,
        "bbox": [[x0, 0], [x1, 0], [x1, 28], [x0, 28]],
        **({"method": method} if method else {}),
    }


def conflicts(raw, detected):
    return refined_caption_conflicts(
        prefixed_label(raw),
        [part(raw, method="complete_line_recognition")],
        detected,
    )


class CaptionPrefixOverlapTests(unittest.TestCase):
    def test_nonliteral_punctuation_on_overlapping_same_role_is_not_another_id(self):
        for raw, role, identifier in (
            ("Compound 71", "Compound /", "71"),
            ("Example A-29", "Example /", "A-29"),
            ("Cpd. 18B", "Cpd. /", "18B"),
        ):
            with self.subTest(raw=raw):
                self.assertFalse(
                    conflicts(raw, [part(role, 0, 120), part(identifier, 90, 150)])
                )

    def test_independent_numeric_disagreement_survives_role_overlap(self):
        self.assertTrue(
            conflicts("Compound 71", [part("Compound /", 0, 120), part("72", 90, 150)])
        )

    def test_complete_prefixed_disagreement_cannot_use_a_locator_exemption(self):
        self.assertTrue(
            conflicts("Compound 71", [part("Compound 72", 0, 120), part("71", 90, 150)])
        )

    def test_different_role_and_disjoint_punctuation_remain_unresolved(self):
        self.assertTrue(
            conflicts("Compound 71", [part("Example /", 0, 120), part("71", 90, 150)])
        )
        self.assertTrue(
            conflicts("Compound 71", [part("Compound /", 0, 70), part("71", 90, 150)])
        )

    def test_weak_contained_different_row_or_incomplete_number_is_not_a_boundary(self):
        for number in (
            part("71", 90, 150, score=0.84),
            part("71", 20, 80),
            part("7", 90, 150),
            part("71B", 90, 150),
            {**part("71", 90, 150), "bbox": [[90, 40], [150, 40], [150, 68], [90, 68]]},
            {**part("71", 90, 150), "bbox": None},
        ):
            with self.subTest(number=number):
                self.assertTrue(
                    conflicts("Compound 71", [part("Compound /", 0, 120), number])
                )

    def test_alphanumeric_role_fragments_and_independent_source_claims_still_veto(self):
        for detected in (
            [part("Compound A", 0, 120), part("71", 90, 150)],
            [part("Compound 7", 0, 120), part("72", 90, 150)],
            [part("Compound /", 0, 120), part("71", 90, 150), part("72", 180, 220)],
            [
                part("Compound /", 0, 120),
                part("71", 90, 150),
                part("Intermediate", 180, 260),
            ],
        ):
            with self.subTest(detected=detected):
                self.assertTrue(conflicts("Compound 71", detected))

    def test_serialized_formal_caption_replays_the_same_conflict_guard(self):
        observations = [
            {
                "method": method,
                "text": "71",
                "raw_text": "Compound 71",
                "confidence": 0.98,
                "bbox": [16, 176, 164, 200],
                "parts": [part("Compound 71", method="complete_line_recognition")],
                "detection_parts": [part("Compound /", 0, 120), part("71", 90, 150)],
            }
            for method in ("cell_ocr_400dpi", "cell_ocr_600dpi")
        ]
        packet = {
            "cpd": "Compound 71",
            "structure_id": "controlled-caption-source",
            "page_no": 1,
            "struct_x0": 20,
            "struct_y0": 30,
            "struct_x1": 160,
            "struct_y1": 180,
            "binding_rule": "original_caption_cell",
            "exact_caption_evidence": {
                "bbox": [20, 180, 160, 196],
                "reading_bbox": [16, 176, 164, 200],
                "page_no": 1,
                "ownership": {},
                "observations": observations,
            },
        }
        stored = json.loads(json.dumps(packet))
        self.assertTrue(valid_caption_binding_evidence(stored))
        stored["exact_caption_evidence"]["observations"][0]["detection_parts"][1][
            "text"
        ] = "72"
        self.assertFalse(valid_caption_binding_evidence(stored))

        stored = json.loads(json.dumps(packet))
        stored["exact_caption_evidence"]["observations"].insert(
            0,
            {
                "method": "native_cell",
                "text": "Compound 72",
                "bbox": [16, 176, 164, 200],
            },
        )
        self.assertFalse(valid_caption_binding_evidence(stored))


if __name__ == "__main__":
    unittest.main()
