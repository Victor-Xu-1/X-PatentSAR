"""Controlled scanned headings: source conflicts, typed bounds and serialized proof."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.heading_observation import observe_heading
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration


class HeadingObservationTests(unittest.TestCase):
    @staticmethod
    def observe(*, shadow=False, engine=None, fontsize=11, wrapped=False):
        with fitz.open() as original:
            page = original.new_page(width=500, height=400)
            page.insert_text(
                (40, 65),
                "Compounds 73 and" if wrapped else "Compounds 73 and 74",
                fontsize=fontsize,
            )
            if wrapped:
                page.insert_text((40, 65 + fontsize * 1.4), "74", fontsize=fontsize)
            words = page.get_text("words")
            bounds = [
                min(w[0] for w in words),
                min(w[1] for w in words),
                max(w[2] for w in words),
                max(w[3] for w in words),
            ]
            pixels = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes(
                "png"
            )
        with fitz.open() as document:
            page = document.new_page(width=500, height=400)
            page.insert_image(page.rect, stream=pixels)
            page.insert_text((40, 380), "Native footer only", fontsize=8)
            if shadow:
                page.insert_text((40, 65), "Compound 75", fontsize=11, render_mode=3)
            source = {
                "text": "Compound 795",
                "bbox": bounds,
                "source": "page_ocr",
                "geometry_space": "rendered",
            }
            digest = hashlib.sha256(document.tobytes(no_new_id=True)).hexdigest()
            if engine is not None:
                with patch(
                    "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                    return_value=engine,
                ):
                    return observe_heading(page, source, digest)
            return observe_heading(page, source, digest)

    @classmethod
    def setUpClass(cls):
        cls.baseline = cls.observe()
        if proved_heading_declaration(cls.baseline) is None:
            raise AssertionError("Controlled source must qualify before mutation tests")

    def test_unscored_provider_is_only_a_locator_not_a_proved_declaration(self):
        proof = self.observe(engine=("paddlex", None))
        self.assertEqual(proof["status"], "unresolved")
        self.assertEqual(proof["observations"], [])
        self.assertIsNone(proved_heading_declaration(proof))

    def test_actual_native_shadow_conflict_cannot_be_outvoted_by_two_raster_reads(self):
        proof = self.observe(shadow=True)
        self.assertEqual(len(proof["observations"]), 2)
        self.assertIn("75", proof["native_source"]["text"])
        self.assertEqual(proof["status"], "unresolved")
        self.assertIsNone(proved_heading_declaration(proof))

    def test_known_independent_detector_identifier_conflicts_remain_unresolved(self):
        proof = copy.deepcopy(self.baseline)
        proof["observations"][0]["detection_parts"].append(
            {
                "text": "Compound 75",
                "confidence": 0.99,
                "bbox": None,
                "coordinate_space": "cell_ink_crop_pixels",
            }
        )
        self.assertIsNone(proved_heading_declaration(proof))

    def test_boolean_low_or_invalid_scores_cannot_qualify_original_text(self):
        for score in (True, "0.99", None, float("nan"), 0.7):
            proof = copy.deepcopy(self.baseline)
            proof["observations"][0]["parts"][0]["confidence"] = score
            with self.subTest(score=repr(score)):
                self.assertIsNone(proved_heading_declaration(proof))

    def test_missing_frames_wrong_dpi_or_out_of_scope_pixels_reject_saved_proof(self):
        missing = copy.deepcopy(self.baseline)
        missing["rendered_frames"] = []
        dpi = copy.deepcopy(self.baseline)
        dpi["rendered_frames"][0]["dpi"] = True
        shape = copy.deepcopy(self.baseline)
        shape["rendered_frames"][0]["shape"] = [9000, 9000, 3]
        raw = copy.deepcopy(self.baseline)
        raw["observations"][1]["raw_text"] = "Compounds 73 and 75"
        bounds = copy.deepcopy(self.baseline)
        bounds["nomination"]["bbox"][2] += 500
        for proof in (missing, dpi, shape, raw, bounds):
            with self.subTest(kind=list(proof)):
                self.assertIsNone(proved_heading_declaration(proof))

    def test_current_serialized_observations_recompute_the_literal_members(self):
        proof = json.loads(json.dumps(self.baseline))
        self.assertEqual(proved_heading_declaration(proof)["identifiers"], ["73", "74"])
        self.assertEqual(proof["nomination"]["text"], "Compound 795")

    def test_missing_or_out_of_frame_ink_cannot_be_relabelled_as_a_complete_read(self):
        for field, value in (
            ("ink_crop_pixels", None),
            ("ink_crop_pixels", [0, 0, 9000, 9000]),
            ("border_pixels", True),
        ):
            proof = copy.deepcopy(self.baseline)
            proof["observations"][0][field] = value
            with self.subTest(field=field):
                self.assertIsNone(proved_heading_declaration(proof))

    def test_large_scanned_heading_does_not_inherit_small_assay_font_assumptions(self):
        for wrapped in (False, True):
            proof = self.observe(fontsize=22, wrapped=wrapped)
            with self.subTest(wrapped=wrapped):
                declaration = proved_heading_declaration(proof)
                self.assertIsNotNone(
                    declaration,
                    [
                        (reading["raw_text"], reading["confidence"])
                        for reading in proof["observations"]
                    ],
                )
                self.assertEqual(declaration["identifiers"], ["73", "74"])


if __name__ == "__main__":
    unittest.main()
