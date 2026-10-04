"""Native Ketcher/Indigo unknown stereo is never determined by its SMILES getter."""

import unittest

from manual_stereo_fixtures import structure_block, unknown_block
from rdkit import Chem
from test_web_support import WebFixture

from patent_sar_extractor.web.correction_chemistry import (
    converted_smiles,
    validate_structure,
)
from patent_sar_extractor.web.molecule_drawing import draw_smiles
from patent_sar_extractor.web.prediction_identity import prediction_eligible

# Captured from Ketcher Standalone 3.18.0 on controlled FC(Cl)Br input, not a patent.
NATIVE_UNKNOWN = """
  -INDIGO-10042612152D

  0  0  0  0  0  0  0  0  0  0  0 V3000
M  V30 BEGIN CTAB
M  V30 COUNTS 4 3 0 0 0
M  V30 BEGIN ATOM
M  V30 1 F 8.80352 -2.625 0.0 0
M  V30 2 C 7.9375 -3.125 0.0 0 CFG=1
M  V30 3 Cl 7.07147 -2.625 0.0 0
M  V30 4 Br 7.9375 -4.125 0.0 0
M  V30 END ATOM
M  V30 BEGIN BOND
M  V30 1 1 1 2
M  V30 2 1 2 3 CFG=2
M  V30 3 1 2 4
M  V30 END BOND
M  V30 BEGIN COLLECTION
M  V30 MDLV30/STEABS ATOMS=(1 2)
M  V30 END COLLECTION
M  V30 END CTAB
M  END
"""


NATIVE_UNKNOWN_DOUBLE = """
  -INDIGO-10042612372D

  0  0  0  0  0  0  0  0  0  0  0 V3000
M  V30 BEGIN CTAB
M  V30 COUNTS 4 3 0 0 0
M  V30 BEGIN ATOM
M  V30 1 F 9.21974 -3.466 0.0 0
M  V30 2 C 8.29959 -3.07445 0.0 0 CFG=1
M  V30 3 C 7.50041 -3.67555 0.0 0
M  V30 4 F 6.58026 -3.284 0.0 0
M  V30 END ATOM
M  V30 BEGIN BOND
M  V30 1 1 1 2
M  V30 2 2 2 3 CFG=2
M  V30 3 1 3 4
M  V30 END BOND
M  V30 BEGIN COLLECTION
M  V30 MDLV30/STEABS ATOMS=(1 2)
M  V30 END COLLECTION
M  V30 END CTAB
M  END
"""


class NativeStereoConversionTests(WebFixture, unittest.TestCase):
    def test_explicit_unknown_atom_cfg_cannot_acquire_unique_prediction_identity(self):
        block = structure_block("FC(Cl)Br", v3000=True)
        lines = block.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("M  V30 2 C "):
                lines[index] = line + " CFG=3"
        block = "\n".join(lines) + "\n"
        self.assertEqual(converted_smiles(block), "FC(Cl)Br")
        self.assertFalse(prediction_eligible("FC(Cl)Br", block))

    def test_cyclic_mixed_absolute_and_unknown_native_groups_keep_defined_center(self):
        molecule = Chem.MolFromSmiles("C[C@H]1CCCC[C@H]1F |a:1,6|")
        from rdkit.Chem import rdDepictor

        rdDepictor.Compute2DCoords(molecule)
        bond = molecule.GetBondBetweenAtoms(6, 7)
        self.assertEqual(bond.GetBeginAtomIdx(), 6)
        bond.SetBondDir(Chem.BondDir.UNKNOWN)
        block = Chem.MolToMolBlock(molecule, forceV3000=True)
        result = converted_smiles(block)
        self.assertEqual(
            result.count("@"),
            1,
            "only explicit unknown center can lose determinate parity",
        )
        validate_structure(block, result)

    def test_unknown_mdl_overrides_vendor_determinate_smiles_without_rewriting_source(
        self,
    ):
        self.assertEqual(converted_smiles(NATIVE_UNKNOWN), "FC(Cl)Br")
        validate_structure(NATIVE_UNKNOWN, "FC(Cl)Br")
        with self.assertRaises(ValueError):
            validate_structure(NATIVE_UNKNOWN, "F[C@H](Br)Cl")
        self.assertIn("CFG=1", NATIVE_UNKNOWN)
        self.assertIn("CFG=2", NATIVE_UNKNOWN)
        self.assertTrue(draw_smiles("FC(Cl)Br", NATIVE_UNKNOWN).startswith(b"\x89PNG"))

    def test_authenticated_converter_uses_no_queue_or_model_and_retains_empty(self):
        with self.client() as client:
            response = client.post(
                "/api/v1/chemistry/structure", json={"molfile": NATIVE_UNKNOWN}
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"smiles": "FC(Cl)Br"})
            empty = Chem.MolToMolBlock(Chem.Mol(), forceV3000=True)
            self.assertEqual(
                client.post(
                    "/api/v1/chemistry/structure", json={"molfile": empty}
                ).json(),
                {"smiles": None},
            )
            self.assertEqual(client.get("/api/v1/jobs").json()["items"], [])
            client.headers.pop("X-CSRF-Token")
            self.assertEqual(
                client.post(
                    "/api/v1/chemistry/structure", json={"molfile": NATIVE_UNKNOWN}
                ).status_code,
                403,
            )

    def test_defined_stereo_is_preserved_and_unsupported_forms_fail_closed(self):
        with self.client() as client:
            for smiles in (
                "F[C@@H](Cl)Br",
                "F/C=C/F",
                "[13CH3][C@H](O)C(=O)[O-].[Na+]",
            ):
                block = structure_block(smiles, v3000=True)
                response = client.post(
                    "/api/v1/chemistry/structure", json={"molfile": block}
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    response.json()["smiles"],
                    Chem.MolToSmiles(Chem.MolFromSmiles(smiles)),
                )
            for group in ("o1:1", "&1:1"):
                block = structure_block(f"F[C@H](Cl)Br |{group}|", v3000=True)
                response = client.post(
                    "/api/v1/chemistry/structure", json={"molfile": block}
                )
                self.assertEqual(response.status_code, 422, response.text)
            for body in (
                {"molfile": "invalid"},
                {"molfile": NATIVE_UNKNOWN, "command": "anything"},
            ):
                self.assertEqual(
                    client.post("/api/v1/chemistry/structure", json=body).status_code,
                    422,
                )
            self.assertEqual(
                client.post(
                    "/api/v1/chemistry/structure", json={"molfile": "x" * 131073}
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    "/api/v1/chemistry/structure", json={"molfile": "x" * (1024 * 1024)}
                ).status_code,
                413,
            )

    def test_unknown_double_uses_same_mdl_authority(self):
        for version in (False, True):
            _, block = unknown_block("double", v3000=version)
            self.assertEqual(converted_smiles(block), "FC=CF")
        self.assertEqual(converted_smiles(NATIVE_UNKNOWN_DOUBLE), "FC=CF")
        validate_structure(NATIVE_UNKNOWN_DOUBLE, "FC=CF")
        self.assertFalse(prediction_eligible("FC=CF", NATIVE_UNKNOWN_DOUBLE))


if __name__ == "__main__":
    unittest.main()
