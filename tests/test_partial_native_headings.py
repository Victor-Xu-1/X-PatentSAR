"""Complete optical titles conserve every qualified original native fragment."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.heading_original_replay import validate_original_heading
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from tests.test_native_heading_coverage import heading, original_cell


class PartialNativeHeadingTests(unittest.TestCase):
    def setUp(self):
        self.factory = self.enterContext(
            patch(
                "patent_sar_extractor.core.page_ocr_cache._build_ocr_engine",
                side_effect=AssertionError(
                    "No native model in generated source checks"
                ),
            )
        )
        self.auxiliary = self.enterContext(
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=None,
            )
        )

    def tearDown(self):
        self.assertEqual(self.factory.call_count, 0)

    def observe(self, page, nomination, text, *, score=0.99):
        calls = []

        def reader(image, *, use_det, use_cls):
            calls.append((image.shape, use_det, use_cls))
            return ([], None) if use_det else ([[text, score]], None)

        with patch(
            "patent_sar_extractor.core.heading_observation.get_ocr_engine",
            return_value=("rapidocr", reader),
        ):
            proof = heading(page, nomination)
        return proof, calls

    def test_outlined_nonfinal_prefix_is_confirmed_without_discarding_native_id(self):
        for prefix in ("Intermediate", "Preparation of intermediate"):
            with (
                self.subTest(prefix=prefix),
                original_cell(prefix=prefix, outlined=True) as (_, page, nomination),
            ):
                proof, calls = self.observe(page, nomination, prefix + " Compound 11")
                saved = json.loads(json.dumps(proof))
                declaration = proved_heading_declaration(saved)
                self.assertIsNotNone(declaration)
                self.assertEqual(declaration["role"], "intermediate_section")
                self.assertEqual(saved["native_source"]["text"], "Compound 11")
                self.assertEqual(len(calls), 2)
                self.assertEqual(self.auxiliary.call_count, 0)
                validate_original_heading(page, saved)

    def test_native_locator_remains_a_fragment_not_a_full_source_veto(self):
        with original_cell(prefix="Intermediate", outlined=True) as (_, page, hint):
            nomination = {**hint, "source": "native", "text": "Compound 11"}
            proof, _ = self.observe(page, nomination, "Intermediate Compound 11")
            self.assertIsNotNone(proved_heading_declaration(proof))
            self.assertEqual(proof["nomination"], nomination)
            validate_original_heading(page, proof)

    def test_complete_native_text_never_needs_a_replacement_reading(self):
        with (
            original_cell() as (_, page, nomination),
            patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                side_effect=AssertionError(
                    "Complete native title needs no optical work"
                ),
            ),
        ):
            proof = heading(page, nomination)
            self.assertIsNotNone(proved_heading_declaration(proof))
            self.assertEqual(proof["observations"], [])

    def test_terminal_preparation_title_keeps_its_exact_original_suffix(self):
        with original_cell(
            prefix="Synthesis of", value="Compound 008B", outlined=True
        ) as (
            _,
            page,
            hint,
        ):
            proof, calls = self.observe(page, hint, "Synthesis of Compound 008B")
            declaration = proved_heading_declaration(proof)
            self.assertIsNotNone(declaration)
            self.assertEqual(declaration["role"], "compound_heading")
            self.assertEqual(declaration["identifier"], "008B")
            self.assertEqual(len(calls), 2)
            validate_original_heading(page, proof)

    def test_complete_native_source_cannot_be_replaced_with_added_role_words(self):
        from patent_sar_extractor.core.heading_native_claims import (
            native_heading_agrees,
        )

        with original_cell() as (_, page, hint):
            proof = heading(page, hint)
            self.assertTrue(native_heading_agrees(proof, "Compound 11"))
            self.assertFalse(native_heading_agrees(proof, "Intermediate Compound 11"))

    def test_original_native_negative_role_cannot_be_dropped_during_optical_recovery(
        self,
    ):
        with original_cell(value="Intermediate Compound 11") as (_, page, hint):
            x, y = hint["bbox"][2] + 0.2, hint["bbox"][1] + 1
            page.draw_rect(fitz.Rect(x, y, x + 0.4, y + 0.4), fill=(0, 0, 0))
            proof, _ = self.observe(page, hint, "Compound 11")
            self.assertIsNone(proved_heading_declaration(proof))

    def test_different_native_locator_cannot_borrow_the_actual_native_id(self):
        with original_cell(prefix="Intermediate", outlined=True) as (_, page, hint):
            hint = {**hint, "source": "native", "text": "Compound 12"}
            proof, _ = self.observe(page, hint, "Intermediate Compound 11")
            self.assertIsNone(proved_heading_declaration(proof))

    def test_known_native_identifier_or_word_cannot_be_changed_or_embedded(self):
        for text in (
            "Intermediate Compound 12",
            "Intermediate Compound 111",
            "Intermediate Compound 11A",
            "Intermediate Conpound 11",
            "Intermediate Compound 11 and 12",
            "Compound 11.",
            "Compound 11: Synthesis",
        ):
            with (
                self.subTest(text=text),
                original_cell(prefix="Intermediate", outlined=True) as (_, page, hint),
            ):
                proof, _ = self.observe(page, hint, text)
                self.assertIsNone(proved_heading_declaration(proof))

    def test_missing_or_low_score_whole_read_cannot_supply_the_outlined_role(self):
        for text, score in (("Compound 11", 0.99), ("Intermediate Compound 11", 0.7)):
            with (
                self.subTest(text=text, score=score),
                original_cell(prefix="Intermediate", outlined=True) as (_, page, hint),
            ):
                proof, _ = self.observe(page, hint, text, score=score)
                self.assertIsNone(proved_heading_declaration(proof))

    def test_hidden_or_overpainted_native_text_cannot_grant_partial_agreement(self):
        for mode in ("hidden", "covered"):
            with (
                self.subTest(mode=mode),
                original_cell(prefix="Intermediate", outlined=True) as (_, page, hint),
            ):
                word = next(word for word in page.get_text("words") if word[4] == "11")
                if mode == "hidden":
                    page.insert_text((word[0], 65), "12", fontsize=11, render_mode=3)
                else:
                    page.draw_rect(fitz.Rect(word[:4]), color=None, fill=(1, 1, 1))
                proof, _ = self.observe(page, hint, "Intermediate Compound 11")
                self.assertIsNone(proved_heading_declaration(proof))

    def test_partial_title_still_requires_original_pixels_and_complete_inventory(self):
        with original_cell(prefix="Intermediate", outlined=True) as (_, page, hint):
            proof, _ = self.observe(page, hint, "Intermediate Compound 11")
            self.assertIsNotNone(proved_heading_declaration(proof))
            mutations = []
            for field, value in (("refusal", "paint_budget"), ("paints", [])):
                changed = copy.deepcopy(proof)
                changed["native_window"][field] = value
                mutations.append(changed)
            changed = copy.deepcopy(proof)
            del changed["native_window"]
            mutations.append(changed)
            changed = copy.deepcopy(proof)
            changed["observations"][0]["detection_parts"].append(
                {
                    "text": "Compound 12",
                    "confidence": 0.99,
                    "bbox": None,
                    "coordinate_space": "cell_ink_crop_pixels",
                }
            )
            mutations.append(changed)
            for changed in mutations:
                changed["status"] = "confirmed"
                self.assertIsNone(proved_heading_declaration(changed))
            page.draw_rect(fitz.Rect(41, 55, 43, 57), fill=(0, 0, 0))
            with self.assertRaises(ValueError):
                validate_original_heading(page, proof)


if __name__ == "__main__":
    unittest.main()
