"""Closed-cell refinement conserves original ink, bounded reads and conflicts."""

import copy
import json
import unittest

import fitz

from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.source_cell_pixels import observe_closed_cell
from tests.test_heading_ruled_source import observe_original


class HeadingCellWitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads(
            json.dumps(
                observe_original("Compound 82A", ruled=True, retained_window=True)
            )
        )
        if proved_heading_declaration(cls.original) is None:
            raise AssertionError("Actual closed-cell control must qualify first")

    def test_malformed_original_detector_scores_refuse_instead_of_crashing(self):
        for score in (True, None, "0.99", float("nan"), -0.1, 1.01):
            changed = copy.deepcopy(self.original)
            changed["original_heading"]["observations"][0]["detection_parts"][0][
                "confidence"
            ] = score
            with self.subTest(score=score):
                self.assertIsNone(proved_heading_declaration(changed))
        changed = copy.deepcopy(self.original)
        changed["original_heading"]["observations"][0]["detection_parts"][0][
            "confidence_valid"
        ] = False
        self.assertIsNone(proved_heading_declaration(changed))

    def test_same_identifier_does_not_allow_a_literal_elution_note_to_disappear(self):
        changed = copy.deepcopy(self.original)
        changed["original_heading"]["observations"][0]["detection_parts"][0].update(
            text="Compound 82A first eluting isomer", confidence=0.99
        )
        self.assertIsNone(proved_heading_declaration(changed))

    def test_refined_crop_must_retain_the_entire_original_cell_ink_envelope(self):
        for resolution in (0, 1):
            changed = copy.deepcopy(self.original)
            crop = changed["observations"][resolution]["ink_crop_pixels"]
            crop[0] += 1
            with self.subTest(resolution=resolution):
                self.assertIsNone(proved_heading_declaration(changed))

    def test_changed_original_document_or_cell_coordinates_are_not_inherited(self):
        changes = (
            ("original_pdf_sha256", "b" * 64),
            ("page_no", 2),
            ("page_size", [361, 240]),
            ("raster_bounds", None),
            ("version", True),
            ("status", "confirmed"),
        )
        for field, value in changes:
            changed = copy.deepcopy(self.original)
            changed["original_heading"][field] = value
            with self.subTest(field=field):
                self.assertIsNone(proved_heading_declaration(changed))

    def test_saved_pixel_packet_is_bounded_and_cannot_omit_a_resolution(self):
        for mutation in (
            "huge",
            "truncated",
            "tail",
            "wrong_dpi",
            "missing",
            "extra",
            "moved",
        ):
            changed = copy.deepcopy(self.original)
            packet = changed["cell_source"]["pixels"]
            reading = packet["readings"][0]
            if mutation == "huge":
                reading["shape"][0] = 8_000_001
            elif mutation == "truncated":
                reading["mask_hex"] = reading["mask_hex"][:-2]
            elif mutation == "tail":
                reading["mask_hex"] += "00"
            elif mutation == "wrong_dpi":
                reading["dpi"] = 600
            elif mutation == "missing":
                packet["readings"].pop()
            elif mutation == "extra":
                packet["readings"].append(copy.deepcopy(reading))
            else:
                packet["bbox"][0] += 1
            with self.subTest(mutation=mutation):
                self.assertIsNone(proved_heading_declaration(changed))

    @staticmethod
    def witness(*, annotation=False, dashes=None):
        with fitz.open() as document:
            page = document.new_page(width=360, height=160)
            cell = [50, 50, 240, 75]
            page.draw_rect(fitz.Rect(cell), width=0.4, dashes=dashes)
            page.insert_text((70, 68), "Compound 71", fontsize=9.5)
            if annotation:
                # Independent original ink inside the cell, outside the text
                # inset. It must not be thrown away along with a nearby rule.
                page.draw_rect(fitz.Rect(50.8, 60, 51.2, 61), fill=(0, 0, 0), width=0)
            return observe_closed_cell(page, cell)

    def test_unexplained_original_ink_cannot_be_removed_as_ruling_context(self):
        self.assertIsNotNone(self.witness())
        self.assertIsNone(self.witness(annotation=True))

    def test_large_rule_gaps_do_not_acquire_unobserved_edges(self):
        self.assertIsNone(self.witness(dashes="[1 3] 0"))


if __name__ == "__main__":
    unittest.main()
