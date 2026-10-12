"""Native multi-direction chemistry/scale, private H and explicit refusal cases."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rdkit import Chem

from patent_sar_extractor.core.sar.matching import compile_reference
from patent_sar_extractor.core.sar.molecules import (
    chemical_identity,
    read_molfile,
    read_smiles,
)
from patent_sar_extractor.web.sar.matrix_drawing import matrix_drawings
from patent_sar_extractor.web.sar.preview_drawing import render_molecule


class SARMatrixLayoutTests(unittest.TestCase):
    def draw(self, reference, alternatives):
        original = Chem.MolToMolBlock(read_smiles(reference))
        selections = []
        for index, (smiles, atoms, anchor) in enumerate(alternatives):
            candidate = Chem.MolToMolBlock(read_smiles(smiles))
            region = SimpleNamespace(atom_indices=atoms, hydrogen_anchor=anchor)
            proof = compile_reference(
                original, atoms, hydrogen_anchor=anchor
            ).compare_details(candidate)
            self.assertEqual(proof["match_status"], "matched", proof)
            selections.append(
                SimpleNamespace(
                    data=SimpleNamespace(region=region, drawings=None),
                    reference={"id": "reference", "molfile": original},
                    candidate={"id": str(index), "molfile": candidate},
                    proof=proof,
                )
            )
        bytes_before = [item.candidate["molfile"] for item in selections]
        captures = []

        def native(mol, selected, bounds):
            result = render_molecule(mol, selected, bounds)
            captures.append(
                (
                    chemical_identity(mol),
                    result[1],
                    (bounds[0].x, bounds[0].y, bounds[1].x, bounds[1].y),
                )
            )
            return result

        with patch(
            "patent_sar_extractor.web.sar.matrix_drawing.render_molecule", native
        ):
            drawing = matrix_drawings(selections)
        self.assertEqual(drawing.id, "reference")
        self.assertEqual(captures[0][0], chemical_identity(read_molfile(original)))
        self.assertEqual(len({item[2] for item in captures}), 1)
        source_points = captures[0][1]
        for index, item in enumerate(selections):
            self.assertEqual(item.reference["molfile"], original)
            self.assertEqual(item.candidate["molfile"], bytes_before[index])
            self.assertEqual(
                captures[2 * index + 2][0],
                chemical_identity(read_molfile(bytes_before[index])),
            )
            for first, second in zip(source_points, captures[2 * index + 1][1]):
                self.assertAlmostEqual(first[0], second[0], places=5)
                self.assertAlmostEqual(first[1], second[1], places=5)
        return selections

    def test_distinct_single_site_directions_use_one_reference_and_complete_camera(
        self,
    ):
        self.draw(
            "COc1ccc(Cl)cc1",
            [
                ("CCOc1ccc(Cl)cc1", [0, 1], None),
                ("CCCOc1ccc(Cl)cc1", [0, 1], None),
                ("COc1ccc(Br)cc1", [6], None),
            ],
        )

    def test_private_h_and_other_region_share_original_atom_coordinates(self):
        self.draw(
            "c1ccccc1Cl",
            [
                ("COc1ccccc1Cl", [], 0),
                ("Nc1ccccc1Cl", [], 0),
                ("c1ccccc1Br", [6], None),
            ],
        )

    def test_two_port_linkers_do_not_force_separate_fixed_ends_together(self):
        result = self.draw(
            "c1ccccc1COCc1ccncc1",
            [
                ("c1ccccc1COCCc1ccncc1", [6, 7, 8], None),
                ("c1ccccc1COCCCc1ccncc1", [6, 7, 8], None),
            ],
        )
        self.assertTrue(
            all(item.data.drawings.layout == "fixed_component" for item in result)
        )

    def test_stereo_isotopes_charge_and_salts_survive_multi_candidate_redraw(self):
        self.draw(
            "COCC[C@H]([13CH3])[NH3+].[Cl-]",
            [
                ("CCOCC[C@H]([13CH3])[NH3+].[Cl-]", [0, 1], None),
                ("CCCOCC[C@H]([13CH3])[NH3+].[Cl-]", [0, 1], None),
            ],
        )

    def test_six_different_sizes_are_not_independently_scaled(self):
        self.draw(
            "COc1ccc(Cl)cc1",
            [("C" * count + "Oc1ccc(Cl)cc1", [0, 1], None) for count in range(2, 8)],
        )
