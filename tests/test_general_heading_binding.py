"""Original heading/diagram ownership across layouts, without scientific models."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.core.binding_source_headings import (
    observed_heading_blocks,
    select_heading_bindings,
)
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy


class GeneralHeadingBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="patentsar-heading-regression-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def document(self, heading="[0023] Example 17: Preparation", *, step=True):
        doc = fitz.open()
        page = doc.new_page(width=500, height=600)
        page.insert_text((60, 70), heading, fontsize=11)
        # Controlled drawing and a matching original-PDF crop, not a fabricated ID.
        polygon = [
            (140, 120),
            (180, 100),
            (220, 120),
            (220, 170),
            (180, 190),
            (140, 170),
            (140, 120),
        ]
        page.draw_polyline(polygon, color=(0, 0, 0), width=1.5)
        page.draw_line((220, 120), (270, 95), color=(0, 0, 0), width=1.5)
        if step:
            page.insert_text(
                (60, 260), "[0024] A. Synthesis of an intermediate", fontsize=11
            )
        return doc

    def structure(self, doc, identity="S1", bounds=(125, 90, 285, 210)):
        image = self.root / f"{identity}.png"
        doc[0].get_pixmap(
            matrix=fitz.Matrix(150 / 72, 150 / 72), clip=fitz.Rect(bounds), alpha=False
        ).save(image)
        return dict(
            zip(("x0", "y0", "x1", "y1"), bounds),
            id=identity,
            idx=int(identity[1:]),
            page_no=1,
            image_path=str(image),
        )

    def select(self, doc, structures):
        blocks = observed_heading_blocks(doc, [0], {})
        return select_heading_bindings(
            doc, structures, blocks, {}, str(self.root / "binding"), {}
        )

    def test_paragraph_prefixes_and_ocr_joined_prefix_preserve_identifier(self):
        for text, label in (
            ("[0023] Example 17: Preparation", "17"),
            ("[0023]Example17B: Preparation", "17B"),
            ("Preparation of Compound 3-2: Product", "3-2"),
            ("Synthesis of Example 103A: Product", "103A"),
        ):
            with self.subTest(text=text), self.document(text) as doc:
                self.assertEqual(
                    [b["cpd"] for b in observed_heading_blocks(doc, [0], {})],
                    [f"Compound {label}"],
                )

    def test_scanned_paragraph_headings_are_discovered_from_original_observations(self):
        with fitz.open() as doc:
            doc.new_page(width=500, height=600)
            lines = {
                0: [
                    (64, "[0036] Example24: Product"),
                    (240, "[0037] Step 1: reaction"),
                    (340, "As in Example 25, the reagent was added."),
                ]
            }
            self.assertEqual(
                [b["cpd"] for b in observed_heading_blocks(doc, [0], lines)],
                ["Compound 24"],
            )

    def test_prose_references_and_compound_lists_are_not_headings(self):
        for text in (
            "For example 17, a solvent may be used.",
            "Compound 17 was dissolved in solvent.",
            "Example 17 and Example 18",
            "[0023] Step 17: intermediate",
        ):
            with self.subTest(text=text), self.document(text) as doc:
                self.assertEqual(observed_heading_blocks(doc, [0], {}), [])

    def test_single_standalone_diagram_uses_original_heading_without_caption_ocr(self):
        with self.document() as doc:
            bindings, issues = self.select(doc, [self.structure(doc)])
            self.assertEqual(issues, [])
            self.assertEqual([b["cpd"] for b in bindings], ["Compound 17"])
            self.assertEqual(bindings[0]["binding_rule"], "original_heading_standalone")
            self.assertEqual(
                annotate_binding_accuracy(bindings[0])["accuracy_status"], "confirmed"
            )

    def test_following_step_diagram_cannot_compete_with_original_title_diagram(self):
        with self.document() as doc:
            late = self.structure(doc, "S2", (125, 310, 285, 420))
            bindings, issues = self.select(doc, [self.structure(doc), late])
            self.assertEqual(issues, [])
            self.assertEqual([b["structure_id"] for b in bindings], ["S1"])

    def test_two_diagrams_or_only_step_diagram_remain_unresolved(self):
        with self.document() as doc:
            first = self.structure(doc)
            rival = self.structure(doc, "S2", (300, 90, 460, 210))
            for structures in (
                [first, rival],
                [self.structure(doc, "S3", (125, 310, 285, 420))],
            ):
                bindings, issues = self.select(doc, structures)
                self.assertEqual(bindings, [])
                self.assertEqual(len(issues), 1)

    def test_heading_proof_cannot_survive_changed_crop_bytes_or_identifier(self):
        with self.document() as doc:
            bindings, _ = self.select(doc, [self.structure(doc)])
            self.assertEqual(len(bindings), 1)
            self.assertTrue(
                annotate_binding_accuracy(
                    {**bindings[0], "cpd": "Compound 18", "compound_id": "Compound 18"}
                )["fail_closed"]
            )
            Path(bindings[0]["image_path"]).write_bytes(b"not the original image")
            self.assertTrue(annotate_binding_accuracy(bindings[0])["fail_closed"])


if __name__ == "__main__":
    unittest.main()
