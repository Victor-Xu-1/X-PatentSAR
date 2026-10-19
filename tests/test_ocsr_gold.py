"""Opt-in exact-graph oracle: genuine RDKit depictions and real DECIMER.

These controlled molecules are test inputs, never production patent results.
This gate establishes only the declared depiction corpus, not all-patent accuracy.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from patent_sar_extractor.core.ocsr.engines.decimer_engine import DECIMEREngine
from patent_sar_extractor.core.ocsr.smiles_converter import SmilesConverter

GOLD = (
    "CCO",
    "c1ccccc1",
    "CC(=O)Oc1ccccc1C(=O)O",
    "NC(=O)c1ccccc1",
    "Fc1ccc(Cl)cc1",
    "C[C@H](O)C(=O)O",
)


@unittest.skipUnless(
    os.environ.get("PATENTSAR_RUN_OCSR_GOLD") == "1",
    "Real DECIMER oracle requires an explicitly configured scientific runtime",
)
class OCSROracleTests(unittest.TestCase):
    def test_default_converter_retains_the_declared_halogen_graph(self):
        from rdkit import Chem
        from rdkit.Chem import Draw

        expected = Chem.MolFromSmiles("Fc1ccc(Cl)cc1")
        converter = SmilesConverter(["decimer"], [], timeout=180)
        self.addCleanup(converter.close)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "original.png"
            Draw.MolToImage(expected, size=(700, 500)).save(image)
            original = image.read_bytes()
            result = converter.convert_one(
                {
                    "cpd": "Example 17",
                    "structure_id": "synthetic-halogen-control",
                    "image_path": str(image),
                    "page_no": 1,
                },
                preprocess_dir=str(root / "prepared"),
            )
            self.assertEqual(result["OCSR_status"], "success", result)
            self.assertEqual(
                result["canonical_smiles"],
                Chem.MolToSmiles(expected, isomericSmiles=True),
            )
            self.assertEqual(result["ocsr_structure_image"], str(image))
            self.assertEqual(image.read_bytes(), original)

    def test_actual_model_matches_declared_atom_bond_and_stereo_truth(self):
        from rdkit import Chem
        from rdkit.Chem import Draw

        engine = DECIMEREngine()
        self.addCleanup(engine.close)
        with tempfile.TemporaryDirectory() as temporary:
            for index, expected in enumerate(GOLD):
                with self.subTest(index=index, expected=expected):
                    molecule = Chem.MolFromSmiles(expected)
                    image = Path(temporary) / f"oracle-{index}.png"
                    Draw.MolToImage(molecule, size=(700, 500)).save(image)
                    result = engine.predict(str(image), timeout=180)
                    self.assertEqual(result["status"], "success", result.get("error"))
                    predicted = Chem.MolFromSmiles(result["raw_smiles"])
                    self.assertIsNotNone(predicted)
                    self.assertEqual(
                        Chem.MolToSmiles(predicted, isomericSmiles=True),
                        Chem.MolToSmiles(molecule, isomericSmiles=True),
                    )
                    self.assertEqual(len(result["model_fingerprint"]), 64)
