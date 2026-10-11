"""Passive molecule previews stay legible without changing selectable atom maps."""

from __future__ import annotations

import base64
import re
import unittest
from types import SimpleNamespace
from xml.etree import ElementTree

from patent_sar_extractor.core.sar.chemistry import prepare_structure
from patent_sar_extractor.core.sar.drawing import (
    draw_molecule_preview,
    draw_structure,
)
from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.molecules import read_molfile
from patent_sar_extractor.web.sar.study_html_charts import ReportFigures


class SARMoleculePreviewTests(unittest.TestCase):
    def test_readable_bonds_keep_all_components_stereo_and_original_atom_map(self):
        for smiles in (
            "COc1ccc(Cl)cc1",
            "[13CH3][C@H](O)C(=O)[O-].[Na+]",
            "COc1ccc([C@@H](F)[C@H](Cl)C(=O)NCCO)cc1",
            "F/C=C/F",
            "CO" + "CCO" * 30 + "c1ccc(Cl)cc1",
        ):
            with self.subTest(smiles=smiles):
                prepared = prepare_structure(smiles)
                self.assertTrue(prepared["eligible"])
                molfile = prepared["molfile"]
                full = draw_structure(molfile, highlighted_atoms=[0])
                preview = draw_molecule_preview(molfile, highlighted_atoms=[0])
                root = ElementTree.fromstring(preview)
                self.assertEqual(root.get("viewBox"), "0 0 360 288")
                # Each original bond remains represented, including stereo strokes.
                bonds = {
                    int(index)
                    for node in root.iter()
                    for index in re.findall(r"\bbond-(\d+)\b", node.get("class", ""))
                }
                self.assertEqual(bonds, set(range(read_molfile(molfile).GetNumBonds())))
                self.assertIn("#3FCC99", preview)
                self.assertEqual(draw_structure(molfile, highlighted_atoms=[0]), full)
                self.assertEqual(prepared["molfile"], molfile)
                self.assertEqual(
                    draw_molecule_preview(molfile, highlighted_atoms=[0]), preview
                )

    def test_regular_bond_is_one_screen_pixel_at_the_actual_table_size(self):
        molfile = prepare_structure("COc1ccc(Cl)cc1")["molfile"]
        root = ElementTree.fromstring(draw_molecule_preview(molfile))
        widths = [
            float(width)
            for node in root.iter()
            if node.get("class", "").startswith("bond-")
            for width in re.findall(r"stroke-width:([0-9.]+)px", node.get("style", ""))
        ]
        self.assertTrue(widths)
        self.assertGreaterEqual(min(widths) * 180 / 360, 1)

    def test_html_molecule_uses_same_preview_while_region_map_keeps_coordinates(self):
        prepared = prepare_structure("COc1ccc(Cl)cc1")
        molecule = SimpleNamespace(**prepared, label="Original <1>")
        figures = ReportFigures()
        html = figures.molecule(molecule)
        svg = base64.b64decode(re.search(r"base64,([^\"]+)", html)[1]).decode()
        self.assertEqual(svg, draw_molecule_preview(prepared["molfile"]))
        self.assertIn("Original &lt;1&gt;", html)
        region = figures.region_map(molecule, [])
        raw = base64.b64decode(re.search(r"base64,([^\"]+)", region)[1]).decode()
        self.assertEqual(ElementTree.fromstring(raw).get("viewBox"), "0 0 1000 800")

    def test_invalid_input_or_highlight_still_refuses_a_preview(self):
        with self.assertRaises(SARInputError):
            draw_molecule_preview("invalid")
        molfile = prepare_structure("CO")["molfile"]
        with self.assertRaisesRegex(SARInputError, "drawing_highlight_invalid"):
            draw_molecule_preview(molfile, highlighted_atoms=[2])
