"""A heading's label/ID space is not a different literal or a guessed ID."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.heading_native_claims import heading_literal
from patent_sar_extractor.core.heading_observation import observe_heading
from patent_sar_extractor.core.heading_original_replay import validate_original_heading
from patent_sar_extractor.core.heading_source_proof import (
    _known_original_agrees,
    proved_heading_declaration,
)
from patent_sar_extractor.core.source_section_roles import section_heading


def original_pair(first, second, *, score=0.99):
    with fitz.open() as original:
        page = original.new_page(width=360, height=180)
        page.insert_text((50, 70), first, fontsize=11)
        words = page.get_text("words")
        bounds = [
            min(w[0] for w in words),
            min(w[1] for w in words),
            max(w[2] for w in words),
            max(w[3] for w in words),
        ]
        pixels = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes("png")
    readings, calls = iter((first, second)), []

    def reader(image, *, use_det, use_cls):
        if use_det:
            return [], None
        calls.append(image.shape)
        return [[next(readings), score]], None

    with fitz.open() as document:
        page = document.new_page(width=360, height=180)
        page.insert_image(page.rect, stream=pixels)
        digest = hashlib.sha256(document.tobytes(no_new_id=True)).hexdigest()
        nomination = {
            "text": "Compound 999",
            "bbox": bounds,
            "source": "page_ocr",
            "geometry_space": "rendered",
        }
        with (
            patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                return_value=("rapidocr", reader),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=None,
            ),
        ):
            proof = observe_heading(page, nomination, digest)
        saved = json.loads(json.dumps(proof))
        if proved_heading_declaration(saved) is not None:
            validate_original_heading(page, saved)
        return saved, calls


class HeadingTokenBoundaryTests(unittest.TestCase):
    def test_same_original_label_control_qualifies_before_variations(self):
        proof, calls = original_pair("Compound 037B", "Compound 037B")
        self.assertEqual(proved_heading_declaration(proof)["identifier"], "037B")
        self.assertEqual(len(calls), 2)

    def test_only_label_to_identifier_whitespace_has_the_same_comparison_identity(self):
        for first, second in (
            ("Compound037B", "Compound 037B"),
            ("Cmpd.037B", "Cmpd. 037B"),
            ("Example007: HTRF assay", "Example 007: HTRF assay"),
            ("Intermediate037B", "Intermediate 037B"),
            (
                "Biological evaluation Compound037B",
                "Biological evaluation Compound 037B",
            ),
            ("Synthesis of Compound037B", "Synthesis of Compound 037B"),
            ("Compounds037B and 091A", "Compounds 037B and 091A"),
            ("化合物037B", "化合物 037B"),
        ):
            with self.subTest(first=first):
                self.assertEqual(heading_literal(first), heading_literal(second))

    def test_two_complete_source_reads_can_differ_only_at_label_token_boundary(self):
        proof, calls = original_pair("Compound037B", "Compound 037B")
        declaration = proved_heading_declaration(proof)
        self.assertIsNotNone(declaration)
        self.assertEqual(declaration["identifier"], "037B")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [r["raw_text"] for r in proof["observations"]],
            ["Compound037B", "Compound 037B"],
        )
        self.assertEqual(proof["nomination"]["text"], "Compound 999")

    def test_original_identifiers_roles_and_unrelated_word_boundaries_are_not_erased(
        self,
    ):
        for first, second in (
            ("Compound037B", "Compound 037"),
            ("Compound037B", "Compound 37B"),
            ("Compound037B", "Cmpd 037B"),
            ("Intermediate Compound037B", "Compound 037B"),
            ("Intermediate Compound037B", "Intermediate Compound 037B"),
            ("Example7: HTRF assay", "Example 7: Synthesis"),
            ("Compound7: Synthesis", "Compound 7"),
            ("Compound7: EC50 10 nM", "Compound 7: EC5010 nM"),
            ("Compounds1 and 2", "Compounds 1 and 3"),
            ("Not Compound037B", "Not Compound 037B"),
        ):
            with self.subTest(first=first, second=second):
                self.assertNotEqual(heading_literal(first), heading_literal(second))

    def test_weak_or_changed_original_identifier_still_cannot_qualify(self):
        weak, _ = original_pair("Compound037B", "Compound 037B", score=0.84)
        changed, _ = original_pair("Compound037B", "Compound 038B")
        self.assertIsNone(proved_heading_declaration(weak))
        self.assertIsNone(proved_heading_declaration(changed))

    def test_known_title_qualifier_word_boundaries_cannot_be_outvoted(self):
        known, _ = original_pair("Compound037B: EC50 10nM", "Compound037B: EC50 10nM")
        self.assertIsNotNone(proved_heading_declaration(known))
        selected = "Compound 037B: EC5010nM"
        self.assertFalse(
            _known_original_agrees(known, section_heading(selected), selected)
        )

    def test_equivalent_text_does_not_allow_source_geometry_or_status_retagging(self):
        proof, _ = original_pair("Compound037B", "Compound 037B")
        self.assertIsNotNone(proved_heading_declaration(proof))
        for mutation in ("source", "status", "frame"):
            changed = copy.deepcopy(proof)
            if mutation == "source":
                changed["observations"][0]["bbox"][0] += 1
            elif mutation == "status":
                changed["status"] = "unresolved"
            else:
                changed["rendered_frames"][0]["shape"][0] += 20
            with self.subTest(mutation=mutation):
                self.assertIsNone(proved_heading_declaration(changed))


if __name__ == "__main__":
    unittest.main()
