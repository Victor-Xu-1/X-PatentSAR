"""Native paired-depiction boundaries; no recognizer, model or production task."""

import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rdkit import Chem

from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.matching import compile_reference
from patent_sar_extractor.core.sar.molecules import (
    chemical_identity,
    read_molfile,
    read_smiles,
)
from patent_sar_extractor.web.sar.preview_alignment import prepare_layout
from patent_sar_extractor.web.sar.preview_drawing import camera, render_molecule


class PreviewAlignmentTests(unittest.TestCase):
    def pair(self, left, right, selected, *, hydrogen_anchor=None, renumber=False):
        a, b = read_smiles(left), read_smiles(right)
        if renumber:
            b = Chem.RenumberAtoms(b, list(reversed(range(b.GetNumAtoms()))))
        first, second = Chem.MolToMolBlock(a), Chem.MolToMolBlock(b)
        region = SimpleNamespace(atom_indices=selected, hydrogen_anchor=hydrogen_anchor)
        proof = compile_reference(
            first, selected, hydrogen_anchor=hydrogen_anchor
        ).compare_details(second)
        self.assertEqual(proof["match_status"], "matched", proof)
        original = (first, second, chemical_identity(a), chemical_identity(b))
        layout = prepare_layout(first, second, region, proof)
        self.assertTrue(layout.aligned)
        self.assertEqual(chemical_identity(layout.reference), original[2])
        self.assertEqual(chemical_identity(layout.candidate), original[3])
        self.assertEqual((first, second), original[:2])
        bounds = camera(layout)
        svg_a, points_a = render_molecule(
            layout.reference, layout.reference_atoms, bounds
        )
        svg_b, points_b = render_molecule(
            layout.candidate, layout.candidate_atoms, bounds
        )
        for i, j in layout.alignment_mapping:
            for left_point, right_point in zip(points_a[i], points_b[j]):
                self.assertAlmostEqual(left_point, right_point, places=5)
        for mol, svg in ((layout.reference, svg_a), (layout.candidate, svg_b)):
            self.assertEqual(
                chemical_identity(read_molfile(Chem.MolToMolBlock(mol))),
                chemical_identity(mol),
            )
            self.assertIn("<svg", svg)
            self.assertNotIn("<script", svg)
        return layout

    def test_leaf_extension_keeps_all_fixed_pixels_at_identical_scale(self):
        layout = self.pair("COc1ccc(Cl)cc1", "CCCOc1ccc(Cl)cc1", [0, 1])
        conformer = layout.candidate.GetConformer()
        for index in layout.candidate_atoms:
            atom = layout.candidate.GetAtomWithIdx(index)
            if atom.IsInRing() or atom.GetDegree() != 2:
                continue
            first, second = (other.GetIdx() for other in atom.GetNeighbors())
            center = conformer.GetAtomPosition(index)
            a, b = (
                conformer.GetAtomPosition(other) - center for other in (first, second)
            )
            angle = math.degrees(
                math.acos(max(-1, min(1, a.DotProduct(b) / (a.Length() * b.Length()))))
            )
            self.assertGreaterEqual(
                angle, 70, "A chain must not fold back over its attachment bond"
            )

    def test_two_port_linker_length_change_keeps_both_fixed_ends(self):
        self.pair("c1ccccc1COCc1ccncc1", "c1ccccc1COCCc1ccncc1", [6, 7, 8])

    def test_linker_expansion_does_not_force_disconnected_fixed_ends_together(self):
        layout = self.pair("COc1ccc(Cl)cc1", "CCCOc1ccc(Cl)cc1", [1])
        self.assertEqual(layout.layout, "fixed_component")
        self.assertLess(len(layout.alignment_mapping), len(layout.mapping))
        conformer = layout.candidate.GetConformer()
        for index in layout.candidate_atoms:
            atom = layout.candidate.GetAtomWithIdx(index)
            if atom.IsInRing() or atom.GetDegree() != 2:
                continue
            first, second = (other.GetIdx() for other in atom.GetNeighbors())
            center = conformer.GetAtomPosition(index)
            a, b = (
                conformer.GetAtomPosition(other) - center for other in (first, second)
            )
            angle = math.degrees(
                math.acos(max(-1, min(1, a.DotProduct(b) / (a.Length() * b.Length()))))
            )
            self.assertGreaterEqual(angle, 70)

    def test_three_port_centre_preserves_fixed_neighbors(self):
        self.pair("COC(c1ccccc1)c1ccncc1", "CON(c1ccccc1)c1ccncc1", [2])

    def test_partial_aromatic_region_uses_complete_original_molecules(self):
        self.pair("Oc1ccccc1N", "Oc1ccncc1N", [4])

    def test_fixed_tetrahedral_and_double_bond_stereo_survive_native_redraw(self):
        self.pair("COCC[C@H](F)Cl", "CCOCC[C@H](F)Cl", [0, 1])
        self.pair("COC/C=C/Cl", "CCOC/C=C/Cl", [0, 1])

    def test_changed_region_stereo_is_not_replaced_by_the_reference_assignment(self):
        layout = self.pair("N[C@H](F)c1ccc(O)cc1", "N[C@@H](F)c1ccc(O)cc1", [0, 1, 2])
        self.assertNotEqual(
            chemical_identity(layout.reference), chemical_identity(layout.candidate)
        )

    def test_unspecified_source_stereo_remains_unspecified(self):
        layout = self.pair("COCC(F)Cl", "CCOCC(F)Cl", [0, 1])
        for mol in (layout.reference, layout.candidate):
            self.assertNotIn("@", chemical_identity(mol))

    def test_isotope_charge_and_all_salt_components_remain_unchanged(self):
        self.pair(
            "COc1ccc([13CH2][NH3+])cc1.[Cl-]",
            "CCOc1ccc([13CH2][NH3+])cc1.[Cl-]",
            [0, 1],
        )

    def test_source_atom_renumbering_and_fixed_symmetry_do_not_rewrite_identity(self):
        layout = self.pair("COc1ccc(Cl)cc1", "CCCOc1ccc(Cl)cc1", [0, 1], renumber=True)
        self.assertGreater(layout.equivalent_mappings, 1)

    def test_hydrogen_reference_and_candidate_keep_original_anchor_binding(self):
        self.pair("c1ccccc1Cl", "COc1ccccc1Cl", [], hydrogen_anchor=0)
        self.pair("COc1ccc(F)cc1Cl", "c1ccc(F)cc1Cl", [0, 1])

    def test_ambiguous_hydrogen_locations_stay_refused(self):
        first, second = (
            Chem.MolToMolBlock(read_smiles(s)) for s in ("COc1ccccc1Cl", "c1ccccc1Cl")
        )
        region = SimpleNamespace(atom_indices=[0, 1], hydrogen_anchor=None)
        proof = compile_reference(first, region.atom_indices).compare_details(second)
        self.assertEqual(proof["match_status"], "ambiguous")
        with self.assertRaises(SARInputError):
            prepare_layout(first, second, region, proof)

    def test_native_constraint_failure_is_explicit_not_an_alignment_claim(self):
        first, second = (
            Chem.MolToMolBlock(read_smiles(s))
            for s in ("COc1ccc(Cl)cc1", "CCOc1ccc(Cl)cc1")
        )
        region = SimpleNamespace(atom_indices=[0, 1], hydrogen_anchor=None)
        proof = compile_reference(first, region.atom_indices).compare_details(second)
        with patch(
            "patent_sar_extractor.web.sar.preview_alignment.rdDepictor.GenerateDepictionMatching2DStructure",
            side_effect=RuntimeError("native unavailable"),
        ):
            result = prepare_layout(first, second, region, proof)
        self.assertFalse(result.aligned)
        self.assertGreaterEqual(result.equivalent_mappings, 1)
        self.assertEqual(result.reason, "depiction_failed")
        self.assertEqual(
            chemical_identity(result.candidate), chemical_identity(read_molfile(second))
        )

    def test_crowded_native_layout_returns_independent_geometry_without_rewriting_chemistry(
        self,
    ):
        first, second = (
            Chem.MolToMolBlock(read_smiles(s))
            for s in ("COc1ccc(Cl)cc1", "CCOc1ccc(Cl)cc1")
        )
        region = SimpleNamespace(atom_indices=[0, 1], hydrogen_anchor=None)
        proof = compile_reference(first, region.atom_indices).compare_details(second)
        with patch(
            "patent_sar_extractor.web.sar.preview_alignment.crowded_chain",
            return_value=True,
        ):
            result = prepare_layout(first, second, region, proof)
        self.assertEqual(result.layout, "independent")
        self.assertEqual(result.reason, "layout_clash")
        self.assertEqual(
            chemical_identity(result.candidate), chemical_identity(read_molfile(second))
        )

    def test_fixed_stereo_or_graph_changes_cannot_enter_an_aligned_preview(self):
        first = Chem.MolToMolBlock(read_smiles("COCC[C@H](F)Cl"))
        for smiles in ("CCOCC[C@@H](F)Cl", "CCOCC[C@H](F)Br"):
            second = Chem.MolToMolBlock(read_smiles(smiles))
            region = SimpleNamespace(atom_indices=[0, 1], hydrogen_anchor=None)
            proof = compile_reference(first, region.atom_indices).compare_details(
                second
            )
            self.assertNotEqual(proof["match_status"], "matched")
            with self.assertRaises(SARInputError):
                prepare_layout(first, second, region, proof)


if __name__ == "__main__":
    unittest.main()
