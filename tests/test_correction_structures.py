"""Strict editable structure/property DTO regressions using the installed RDKit."""

from __future__ import annotations

import unittest

from pydantic import ValidationError
from rdkit import Chem
from rdkit.Chem import rdDepictor

from patent_sar_extractor.web.correction_models import EditableFields


def molfile(smiles: str, *, v3000: bool = False) -> str:
    molecule = Chem.MolFromSmiles(smiles)
    rdDepictor.Compute2DCoords(molecule)
    return Chem.MolToMolBlock(molecule, forceV3000=v3000)


def fields(**changes: object) -> EditableFields:
    return EditableFields.model_validate(
        {"display_id": "Compound 1", "smiles": "CCO", "activities": [], **changes}
    )


class EditableStructureTests(unittest.TestCase):
    def test_v2000_and_v3000_preserve_coordinates_and_match_equivalent_smiles(self):
        for version in (False, True):
            with self.subTest(v3000=version):
                block = molfile("CCO", v3000=version)
                result = fields(smiles="OCC", structure_molfile=block)
                self.assertEqual(result.structure_molfile, block)
                windows_block = block.replace("\n", "\r\n") + "\r\n"
                self.assertEqual(
                    fields(
                        smiles="OCC", structure_molfile=windows_block
                    ).structure_molfile,
                    windows_block,
                )

    def test_chiral_and_double_bond_stereo_must_match_without_loss(self):
        for smiles, wrong in (
            ("N[C@@H](C)C(=O)O", "N[C@H](C)C(=O)O"),
            ("N[C@@H](C)C(=O)O", "NC(C)C(=O)O"),
            ("C/C=C/C", "C/C=C\\C"),
            ("C/C=C/C", "CC=CC"),
        ):
            with self.subTest(smiles=smiles, wrong=wrong):
                block = molfile(smiles)
                self.assertEqual(
                    fields(smiles=smiles, structure_molfile=block).structure_molfile,
                    block,
                )
                with self.assertRaises(ValidationError):
                    fields(smiles=wrong, structure_molfile=block)

    def test_mismatched_isotopes_fragments_or_missing_smiles_are_rejected(self):
        for drawn, supplied in (
            ("CCN", "CCO"),
            ("[13CH3]CO", "CCO"),
            ("CCO.Cl", "CCO"),
            ("CCO", None),
        ):
            with (
                self.subTest(drawn=drawn, supplied=supplied),
                self.assertRaises(ValidationError),
            ):
                fields(smiles=supplied, structure_molfile=molfile(drawn))

    def test_malformed_query_dummy_unsupported_and_oversized_inputs_are_rejected(self):
        query = Chem.MolToMolBlock(Chem.MolFromSmarts("[#6,#7]"))
        valid = molfile("CCO")
        for block in (
            "",
            "not a molfile",
            query,
            molfile("C*"),
            molfile("[Fe]"),
            molfile("C" * 257),
            valid.replace("V2000", "V4000"),
            valid + "\n$$$$\n" + valid,
            valid + "ignored data\nM  END\n",
            valid + "\x00",
            valid + "x" * (128 * 1024),
        ):
            with (
                self.subTest(block=repr(block)[:60]),
                self.assertRaises(ValidationError),
            ):
                fields(structure_molfile=block)

    def test_nonfinite_coordinates_and_impossible_valence_fail_closed(self):
        molecule = Chem.MolFromSmiles("CCO")
        rdDepictor.Compute2DCoords(molecule)
        molecule.GetConformer().SetAtomPosition(0, (float("nan"), 0, 0))
        with self.assertRaises(ValidationError):
            fields(structure_molfile=Chem.MolToMolBlock(molecule))
        molecule = Chem.MolFromSmiles("C(C)(C)(C)(C)C", sanitize=False)
        with self.assertRaises(ValidationError):
            fields(structure_molfile=Chem.MolToMolBlock(molecule, kekulize=False))

    def test_encoded_impossible_stereo_must_not_be_cleaned_into_an_achiral_graph(self):
        molecule = Chem.MolFromSmiles("CC(O)C")
        rdDepictor.Compute2DCoords(molecule)
        molecule.GetAtomWithIdx(1).SetChiralTag(Chem.ChiralType.CHI_TETRAHEDRAL_CW)
        with self.assertRaises(ValidationError):
            fields(smiles="CC(O)C", structure_molfile=Chem.MolToMolBlock(molecule))

    def test_atom_limit_and_molfile_byte_limit_are_bounded_before_parsing(self):
        block = molfile("C" * 256)
        self.assertIsNotNone(
            fields(smiles="C" * 256, structure_molfile=block).structure_molfile
        )
        declared = molfile("CCO", v3000=True).replace(
            "COUNTS 3 2", "COUNTS 999999999 2"
        )
        with self.assertRaises(ValidationError):
            fields(structure_molfile=declared)
        block = molfile("CCO").splitlines(keepends=True)
        block[0] = "文" * 45000 + "\n"
        with self.assertRaises(ValidationError):
            fields(structure_molfile="".join(block))


class EditablePropertyTests(unittest.TestCase):
    def test_hydrogen_bond_counts_must_be_nonnegative_integers(self):
        for key in ("hydrogen_bond_donors", "hydrogen_bond_acceptors"):
            for value in (-1, -1.0):
                with (
                    self.subTest(key=key, value=value),
                    self.assertRaises(ValidationError),
                ):
                    fields(
                        property_overrides={key: value},
                        property_basis_smiles="CCO",
                    )
            for value in (0, 1, 2.0):
                with self.subTest(key=key, value=value):
                    result = fields(
                        property_overrides={key: value},
                        property_basis_smiles="CCO",
                    )
                    self.assertEqual(result.property_overrides[key], value)
                    self.assertIs(type(result.property_overrides[key]), type(value))

    def test_defaults_and_canonically_bound_partial_values(self):
        self.assertEqual(fields().property_overrides, {})
        value = fields(
            property_overrides={
                "logP": -1.2,
                "tpsa": None,
                "hydrogen_bond_donors": 2.0,
            },
            property_basis_smiles="OCC",
        )
        self.assertEqual(
            value.property_overrides,
            {"logP": -1.2, "tpsa": None, "hydrogen_bond_donors": 2.0},
        )
        self.assertEqual(value.property_basis_smiles, "OCC")
        self.assertIsNone(
            fields(smiles=None, property_overrides={"logP": 0}).property_basis_smiles
        )

    def test_explicit_overrides_require_the_exact_effective_graph_basis(self):
        for changes in (
            {"property_overrides": {"logP": 1}},
            {"property_overrides": {"logP": 1}, "property_basis_smiles": "CCN"},
            {
                "smiles": None,
                "property_overrides": {"logP": 1},
                "property_basis_smiles": "CCO",
            },
            {
                "smiles": "F[C@H](Cl)Br",
                "property_overrides": {"logP": 1},
                "property_basis_smiles": "F[C@@H](Cl)Br",
            },
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                fields(**changes)

    def test_value_types_ranges_and_exact_keys_are_not_coerced(self):
        for overrides in (
            {"unknown": 2},
            {"MW": 2},
            {"logP": True},
            {"logP": "2"},
            {"logP": float("nan")},
            {"logP": float("inf")},
            {"molecular_weight": -1},
            {"tpsa": -1},
            {"hydrogen_bond_donors": 1.2},
            {"hydrogen_bond_acceptors": 2.2},
            {"logP": 10**309},
            {"logP": [1]},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                fields(property_overrides=overrides, property_basis_smiles="CCO")
