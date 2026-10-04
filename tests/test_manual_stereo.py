"""Manual MDL representation, redraw identity and unknown-stereo regressions."""

from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from manual_stereo_fixtures import moved_block, structure_block, unknown_block
from pydantic import ValidationError
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from patent_sar_extractor.web.correction_models import EditableFields
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.molecule_drawing import draw_smiles, drawing_url


def editable(smiles: str, block: str) -> EditableFields:
    return EditableFields(
        display_id="Independent manual structure",
        smiles=smiles,
        activities=[],
        structure_molfile=block,
    )


class ManualStereoTests(unittest.TestCase):
    def test_unknown_v2000_and_v3000_are_exact_persistable_representations(self):
        for kind in ("tetra", "double"):
            for version in (False, True):
                with self.subTest(kind=kind, v3000=version):
                    smiles, block = unknown_block(kind, v3000=version)
                    fields = editable(smiles, block)
                    restored = EditableFields.model_validate_json(
                        fields.model_dump_json()
                    )
                    self.assertEqual(restored.structure_molfile, block)
                    self.assertEqual(restored.smiles, smiles)

    def test_raw_representation_and_coordinates_bind_redraw_identity(self):
        for kind in ("tetra", "double"):
            smiles, block = unknown_block(kind, v3000=True)
            plain = drawing_url("project", "A/B", smiles)
            self.assertIn(hashlib.sha256(smiles.encode()).hexdigest(), plain)
            self.assertIn("A%2FB", plain)
            self.assertNotEqual(plain, drawing_url("project", "A/B", smiles, block))
            self.assertNotEqual(
                drawing_url("project", "A/B", smiles, block),
                drawing_url(
                    "project", "A/B", smiles, block.replace("0.000000", "0.100000", 1)
                ),
            )

    def test_redraw_reapplies_source_directions_without_coordinate_regeneration(self):
        for kind in ("tetra", "double"):
            for version in (False, True):
                smiles, block = unknown_block(kind, v3000=version)
                with self.subTest(kind=kind, v3000=version):
                    draw_smiles.cache_clear()
                    source = Chem.MolFromMolBlock(block, removeHs=False)
                    captured = []
                    original = rdMolDraw2D.PrepareMolForDrawing

                    def prepare(molecule, *args, **kwargs):
                        prepared = original(molecule, *args, **kwargs)
                        captured.append(prepared)
                        return prepared

                    with patch.object(rdMolDraw2D, "PrepareMolForDrawing", prepare):
                        rendered = draw_smiles(smiles, block)
                    self.assertTrue(rendered.startswith(b"\x89PNG\r\n\x1a\n"))
                    self.assertEqual(len(captured), 1)
                    prepared = captured[0]
                    for index in range(source.GetNumAtoms()):
                        self.assertLess(
                            (
                                source.GetConformer().GetAtomPosition(index)
                                - prepared.GetConformer().GetAtomPosition(index)
                            ).Length(),
                            1e-8,
                        )
                    bond = prepared.GetBondWithIdx(1)
                    if kind == "tetra":
                        self.assertEqual(bond.GetBondDir(), Chem.BondDir.UNKNOWN)
                        self.assertEqual(
                            prepared.GetAtomWithIdx(1).GetChiralTag(),
                            Chem.ChiralType.CHI_UNSPECIFIED,
                        )
                    else:
                        self.assertEqual(bond.GetStereo(), Chem.BondStereo.STEREOANY)
                        self.assertEqual(bond.GetBondDir(), Chem.BondDir.EITHERDOUBLE)

    def test_unknown_stereo_cannot_be_replaced_by_absolute_smiles(self):
        for kind, supplied in (("tetra", "F[C@H](Cl)Br"), ("double", "F/C=C/F")):
            for version in (False, True):
                _, block = unknown_block(kind, v3000=version)
                with (
                    self.subTest(kind=kind, v3000=version),
                    self.assertRaises(ValidationError),
                ):
                    editable(supplied, block)

    def test_relative_enhanced_groups_remain_fail_closed_and_abs_is_exact(self):
        for group in ("o1:1", "&1:1"):
            block = structure_block(f"F[C@H](Cl)Br |{group}|", v3000=True)
            with self.subTest(group=group), self.assertRaises(ValidationError):
                editable("F[C@H](Cl)Br", block)
        block = structure_block("F[C@H](Cl)Br |a:1|", v3000=True)
        self.assertEqual(editable("F[C@H](Cl)Br", block).structure_molfile, block)

    def test_mixed_defined_and_unknown_stereo_retains_defined_center_without_conflict(
        self,
    ):
        for version in (False, True):
            smiles, block = unknown_block("mixed", v3000=version)
            self.assertEqual(editable(smiles, block).smiles, smiles)
            changed = moved_block(block, v3000=version)
            self.assertEqual(editable(smiles, changed).structure_molfile, changed)
            with self.assertRaises(ValidationError):
                editable(smiles.replace("@", "@@"), block)
            self.assertTrue(draw_smiles(smiles, block).startswith(b"\x89PNG"))

    def test_malformed_stereo_codes_and_unretained_enhanced_metadata_fail_closed(self):
        smiles, block = unknown_block("tetra", v3000=True)
        for corrupt in (
            block.replace("CFG=2", "CFG=9"),
            structure_block("F[C@H](Cl)Br |a:1|", v3000=True).replace(
                "MDLV30/STEABS", "MDLV30/STEREO_UNKNOWN"
            ),
        ):
            with self.assertRaises(ValidationError):
                editable(smiles, corrupt)
        for wrong in ("CCO", "F[C@H](Cl)Br"):
            with self.assertRaises(WebError) as error:
                draw_smiles(wrong, block)
            self.assertEqual(error.exception.code, "invalid_manual_structure")

    def test_defined_stereo_isotopes_charges_fragments_match_exactly(self):
        for smiles in (
            "N[C@@H](C)C(=O)O",
            "F/C=C/F",
            "F/C=C\\F",
            "[13CH3][C@H](O)F.[Na+].[Cl-]",
            "C[NH3+].[Cl-]",
        ):
            for version in (False, True):
                with self.subTest(smiles=smiles, v3000=version):
                    block = structure_block(smiles, v3000=version)
                    self.assertEqual(editable(smiles, block).structure_molfile, block)

    def test_optional_external_render_evidence(self):
        destination = os.environ.get("PATENTSAR_MANUAL_STEREO_EVIDENCE_ROOT")
        if not destination:
            self.skipTest("External rendering evidence is opt-in")
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for kind in ("tetra", "double", "mixed"):
            for version in (False, True):
                smiles, block = unknown_block(kind, v3000=version)
                name = f"{kind}-{'v3000' if version else 'v2000'}"
                (root / f"{name}.mol").write_text(block, encoding="utf-8")
                (root / f"{name}-smiles-only.png").write_bytes(draw_smiles(smiles))
                source = Chem.MolFromMolBlock(block, removeHs=False)
                Chem.ReapplyMolBlockWedging(source)
                prepared = rdMolDraw2D.PrepareMolForDrawing(
                    source,
                    addChiralHs=False,
                    wedgeBonds=False,
                    forceCoords=False,
                )
                drawer = rdMolDraw2D.MolDraw2DCairo(600, 400)
                drawer.drawOptions().prepareMolsBeforeDrawing = False
                drawer.DrawMolecule(prepared)
                drawer.FinishDrawing()
                (root / f"{name}-source-oracle.png").write_bytes(
                    drawer.GetDrawingText()
                )
                # The initial baseline keeps its SMILES-only output as evidence.
                if "molfile" in draw_smiles.__annotations__:
                    (root / f"{name}-manual-redraw.png").write_bytes(
                        draw_smiles(smiles, block)
                    )
