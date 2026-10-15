"""Caption annotations use caption semantics, never bare identifier grammar."""

import unittest

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)


def binding(observations):
    return {
        "cpd": "Compound 84B",
        "structure_id": "controlled-annotated-source",
        "page_no": 1,
        "struct_x0": 20,
        "struct_y0": 30,
        "struct_x1": 160,
        "struct_y1": 180,
        "binding_rule": "original_caption_cell",
        "exact_caption_evidence": {
            "bbox": [20, 180, 160, 196],
            "page_no": 1,
            "ownership": {},
            "observations": observations,
        },
    }


class CaptionReadingSemanticsTests(unittest.TestCase):
    def test_native_complete_literal_elution_caption_keeps_original_identifier(self):
        for raw in (
            "Compound 84B *first eluting isomer",
            "Example 84B second eluting isomer",
        ):
            with self.subTest(raw=raw):
                self.assertTrue(
                    valid_caption_binding_evidence(
                        binding(
                            [
                                {"method": "native_cell", "text": raw},
                            ]
                        )
                    )
                )

    def test_qualified_raster_read_agrees_with_complete_annotated_page_caption(self):
        self.assertTrue(
            valid_caption_binding_evidence(
                binding(
                    [
                        {
                            "method": "page_ocr_cell",
                            "text": "Compound 84B *first eluting isomer",
                        },
                        {
                            "method": "cell_ocr_400dpi",
                            "text": "84B",
                            "confidence": 0.99,
                        },
                    ]
                )
            )
        )

    def test_genuine_native_identity_conflict_or_unknown_prose_is_not_an_elution_note(
        self,
    ):
        for raw in (
            "Compound 85B *first eluting isomer",
            "Compound 84B prepared from Compound 85B",
            "Compound 84B third unknown annotation",
            "Intermediate 84B",
        ):
            with self.subTest(raw=raw):
                self.assertFalse(
                    valid_caption_binding_evidence(
                        binding(
                            [
                                {"method": "native_cell", "text": raw},
                                {
                                    "method": "cell_ocr_400dpi",
                                    "text": "84B",
                                    "confidence": 0.99,
                                },
                                {
                                    "method": "cell_ocr_600dpi",
                                    "text": "84B",
                                    "confidence": 0.99,
                                },
                            ]
                        )
                    )
                )
