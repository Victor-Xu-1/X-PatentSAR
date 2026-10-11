"""Ordinary-H sites remain source-bound, not relaxed background matching."""

import unittest
from unittest.mock import patch

from rdkit import Chem

from patent_sar_extractor.core.sar.chemistry import prepare_structure
from patent_sar_extractor.core.sar.matching import compare_structure, compile_reference
from patent_sar_extractor.core.sar.study_graphs import cut_identity, reference_cut


def block(smiles):
    prepared = prepare_structure(smiles)
    assert prepared["eligible"], prepared["issues"]
    return prepared["molfile"]


class HydrogenSiteTests(unittest.TestCase):
    def test_hydrogen_view_budget_is_explicit_ambiguity_not_partial_success(self):
        matcher = compile_reference(block("COc1c(F)cccc1Cl"), [4])
        with patch("patent_sar_extractor.core.sar.matching.MAX_HYDROGEN_VIEWS", 0):
            proof = matcher.compare(block("COc1ccccc1Cl"))
        self.assertEqual(proof["match_status"], "ambiguous")
        self.assertIn("hydrogen_view_limit_exceeded", proof["reasons"])

    def test_hydrogen_to_substituent_and_reverse_share_the_exact_background(self):
        original = block("COc1ccccc1Cl")
        changed = block("COc1c(F)cccc1Cl")
        proof = compile_reference(original, [], hydrogen_anchor=3).compare_details(
            changed
        )
        self.assertEqual(proof["match_status"], "matched", proof)
        self.assertEqual(proof["variable_atom_indices"], [4])
        self.assertEqual(proof.get("candidate_hydrogen_anchor"), None)
        self.assertEqual(proof["attachment_mapping"], [[3, 3]])
        reverse = compile_reference(changed, [4]).compare_details(original)
        self.assertEqual(reverse["match_status"], "matched", reverse)
        self.assertEqual(reverse["variable_atom_indices"], [])
        self.assertEqual(reverse["candidate_hydrogen_anchor"], 3)
        self.assertEqual(reverse["attachment_mapping"], [[3, 3]])
        hydrogen = reference_cut(original, [], hydrogen_anchor=3)
        fragment = cut_identity(changed, [4], proof["attachment_mapping"])
        self.assertEqual(
            hydrogen["fixed_background_sha256"], fragment["fixed_background_sha256"]
        )
        reverse_fragment = cut_identity(
            original, [], reverse["attachment_mapping"], hydrogen_anchor=3
        )
        self.assertEqual(hydrogen, reverse_fragment)

    def test_hydrogen_to_methyl_requires_no_fixed_atom_change(self):
        proof = compile_reference(
            block("COc1ccccc1Cl"), [], hydrogen_anchor=3
        ).compare_details(block("COc1c(C)cccc1Cl"))
        self.assertEqual(proof["match_status"], "matched", proof)
        self.assertEqual(proof["variable_atom_indices"], [4])

    def test_wrong_location_and_multiple_modifications_are_rejected(self):
        matcher = compile_reference(block("COc1ccccc1Cl"), [], hydrogen_anchor=3)
        for smiles in ("COc1ccc(F)cc1Cl", "COc1c(F)ccc(F)c1Cl", "COc1c(F)cccc1Br"):
            with self.subTest(smiles=smiles):
                self.assertNotEqual(
                    matcher.compare(block(smiles))["match_status"], "matched"
                )

    def test_hydrogen_isotopes_elsewhere_and_components_stay_fixed(self):
        original = "COc1cc([2H])ccc1Cl"
        matcher = compile_reference(block(original), [], hydrogen_anchor=3)
        self.assertEqual(
            matcher.compare(block("COc1c(F)c([2H])ccc1Cl"))["match_status"], "matched"
        )
        self.assertNotEqual(
            matcher.compare(block("COc1c(F)c([3H])ccc1Cl"))["match_status"], "matched"
        )
        spectator = compile_reference(
            block("[Na+].COc1ccccc1Cl"), [], hydrogen_anchor=4
        )
        self.assertEqual(
            spectator.compare(block("[Na+].COc1c(F)cccc1Cl"))["match_status"], "matched"
        )
        for changed in ("[K+].COc1c(F)cccc1Cl", "COc1c(F)cccc1Cl"):
            self.assertNotEqual(
                spectator.compare(block(changed))["match_status"], "matched"
            )

    def test_other_fixed_stereochemistry_cannot_change(self):
        original = block("C[C@H](O)COc1ccccc1Cl")
        mol = Chem.MolFromMolBlock(original, removeHs=False)
        anchor = next(
            atom.GetIdx()
            for atom in mol.GetAtoms()
            if atom.GetIsAromatic() and atom.GetTotalNumHs()
        )
        matcher = compile_reference(original, [], hydrogen_anchor=anchor)
        self.assertEqual(
            matcher.compare(block("C[C@H](O)COc1c(F)cccc1Cl"))["match_status"],
            "matched",
        )
        self.assertNotEqual(
            matcher.compare(block("C[C@@H](O)COc1c(F)cccc1Cl"))["match_status"],
            "matched",
        )

    def test_candidate_hydrogen_positions_are_not_arbitrarily_chosen(self):
        proof = compile_reference(block("Fc1ccccc1"), [0]).compare_details(
            block("c1ccccc1")
        )
        self.assertEqual(proof["match_status"], "ambiguous", proof)
        self.assertIn("ambiguous_region_mapping", proof["reasons"])
        self.assertEqual(proof["variable_atom_indices"], [])
        self.assertEqual(proof["attachment_mapping"], [])

    def test_nonexistent_or_isotopic_hydrogen_is_not_invented(self):
        for source, anchor in (("COc1ccccc1Cl", 1), ("[2H]Oc1ccccc1Cl", 1)):
            with self.assertRaisesRegex(ValueError, "hydrogen_site_unavailable"):
                compile_reference(block(source), [], hydrogen_anchor=anchor)
        with self.assertRaisesRegex(ValueError, "region_invalid_indices"):
            compile_reference(block("COc1ccccc1Cl"), [3], hydrogen_anchor=3)

    def test_hydrogen_boundary_stereo_is_explicitly_unsupported(self):
        with self.assertRaisesRegex(ValueError, "hydrogen_boundary_stereo_unsupported"):
            compile_reference(block("N[C@H](F)c1ccccc1"), [], hydrogen_anchor=1)

    def test_reference_and_candidate_source_bytes_and_normal_matches_remain_unchanged(
        self,
    ):
        source, changed = block("COc1ccccc1Cl"), block("COc1c(F)cccc1Cl")
        saved = (source, changed)
        matcher = compile_reference(source, [], hydrogen_anchor=3)
        for _ in range(2):
            self.assertEqual(matcher.compare(changed)["match_status"], "matched")
        self.assertEqual((source, changed), saved)
        self.assertEqual(
            compare_structure(block("COc1ccc(Cl)cc1"), block("CCOc1ccc(Cl)cc1"), [0])[
                "match_status"
            ],
            "matched",
        )


if __name__ == "__main__":
    unittest.main()
