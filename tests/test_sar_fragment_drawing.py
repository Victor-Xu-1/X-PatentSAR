"""Display-only fragment sizing; full-molecule atom maps keep their authority."""

from __future__ import annotations

import unittest
from xml.etree import ElementTree

from patent_sar_extractor.core.sar.chemistry import prepare_structure
from patent_sar_extractor.core.sar.drawing import draw_fragment, draw_structure
from patent_sar_extractor.core.sar.errors import SARInputError


class SARFragmentDrawingTests(unittest.TestCase):
    def test_fragments_use_a_legible_canvas_without_losing_ports_or_atom_labels(self):
        for smiles in ("F", "F[*:28]", "Cl[*:28]", "[2H]OC(=O)[*:3].[Na+]"):
            with self.subTest(smiles=smiles):
                svg = draw_fragment(smiles)
                root = ElementTree.fromstring(svg)
                self.assertEqual(root.get("viewBox"), "0 0 360 240")
                classes = {element.get("class") for element in root.iter()}
                self.assertIn("atom-0", classes)
                if "*:28" in smiles:
                    self.assertIn("atom-1", classes)
                    self.assertIn("bond-0 atom-0 atom-1", classes)
                self.assertNotIn("<script", svg)
                self.assertEqual(draw_fragment(smiles), svg)

    def test_full_molecule_canvas_and_persisted_atom_coordinates_remain_unchanged(self):
        prepared = prepare_structure("COc1ccc(Cl)cc1")
        self.assertTrue(prepared["eligible"])
        original = prepared["molfile"]
        first = draw_structure(original, highlighted_atoms=[0, 1])
        self.assertEqual(
            ElementTree.fromstring(first["svg"]).get("viewBox"), "0 0 1000 800"
        )
        draw_fragment("Cl[*:28]")
        self.assertEqual(prepared["molfile"], original)
        self.assertEqual(draw_structure(original, highlighted_atoms=[0, 1]), first)
        self.assertEqual([atom["index"] for atom in first["atoms"]], list(range(9)))

    def test_invalid_or_oversized_fragments_still_fail_closed(self):
        for smiles in (None, "", "invalid", "C" * 513, "C" * 8193):
            with (
                self.subTest(smiles=smiles),
                self.assertRaisesRegex(SARInputError, "fragment_drawing_invalid"),
            ):
                draw_fragment(smiles)
