"""Real RDKit proof/port/core fixtures; no patents, models or relaxed matcher."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from rdkit import Chem

from patent_sar_extractor.core.sar.chemistry import prepare_structure
from patent_sar_extractor.core.sar.matching import compile_reference, validate_region
from patent_sar_extractor.core.sar.study_cores import compile_core
from patent_sar_extractor.core.sar.study_graphs import (
    cut_identity,
    graph_description,
    reference_cut,
)


def block(smiles):
    prepared = prepare_structure(smiles)
    if not prepared["eligible"]:
        raise AssertionError(prepared["issues"])
    return prepared["molfile"]


class StudyGraphTests(unittest.TestCase):
    def test_terminal_substituent_returns_proved_indices_and_ports(self):
        reference, candidate = block("COc1ccc(Cl)cc1"), block("CCOc1ccc(Cl)cc1")
        matcher = compile_reference(reference, [0])
        proof = matcher.compare_details(candidate)
        self.assertEqual(proof["match_status"], "matched")
        self.assertEqual(proof["variable_atom_indices"], [0, 1])
        self.assertEqual(proof["attachment_mapping"], [[1, 2]])
        original = reference_cut(reference, [0])
        changed = cut_identity(
            candidate, proof["variable_atom_indices"], proof["attachment_mapping"]
        )
        self.assertNotEqual(original["id"], changed["id"])
        self.assertEqual(
            original["fixed_background_sha256"], changed["fixed_background_sha256"]
        )
        self.assertIn("[*:2]", changed["smiles"])
        self.assertEqual(set(matcher.compare(candidate)), {"match_status", "reasons"})

    def test_two_ended_linker_preserves_connection_correspondence(self):
        reference, candidate = block("COCCN"), block("COCCCN")
        proof = compile_reference(reference, [2, 3]).compare_details(candidate)
        self.assertEqual(proof["match_status"], "matched")
        fragment = cut_identity(
            candidate, proof["variable_atom_indices"], proof["attachment_mapping"]
        )
        self.assertEqual(
            fragment["fixed_background_sha256"],
            reference_cut(reference, [2, 3])["fixed_background_sha256"],
        )
        mol = Chem.MolFromSmiles(fragment["smiles"])
        self.assertEqual(
            sorted(
                atom.GetAtomMapNum()
                for atom in mol.GetAtoms()
                if atom.GetAtomicNum() == 0
            ),
            [2, 5],
        )

    def test_ports_and_stereo_are_invariant_to_candidate_atom_reordering(self):
        reference, candidate = block("C[C@H](F)COC"), block("C[C@H](F)COCC")
        matcher = compile_reference(reference, [5])
        proof = matcher.compare_details(candidate)
        original = cut_identity(
            candidate, proof["variable_atom_indices"], proof["attachment_mapping"]
        )
        mol = Chem.MolFromMolBlock(candidate, removeHs=False)
        changed = Chem.MolToMolBlock(
            Chem.RenumberAtoms(mol, list(reversed(range(mol.GetNumAtoms()))))
        )
        proof = matcher.compare_details(changed)
        self.assertEqual(proof["match_status"], "matched")
        self.assertEqual(
            cut_identity(
                changed, proof["variable_atom_indices"], proof["attachment_mapping"]
            ),
            original,
        )

    def test_fixed_background_stereo_isotope_charge_and_salts_refuse(self):
        cases = [
            ("COc1ccc(Cl)cc1", "CCOc1ccc(Br)cc1", [0]),
            ("COc1ccc(Cl)cc1", "CC[18O]c1ccc(Cl)cc1", [0]),
            ("CNCCN", "C[NH2+]CCCN", [2, 3]),
            ("C[C@H](F)COC", "C[C@@H](F)COCC", [5]),
            ("CC(F)COC", "C[C@H](F)COCC", [5]),
            ("COc1ncccc1.[Na+]", "CCOc1ncccc1.[K+]", [0]),
            ("COc1ncccc1", "CCOc1ncccc1.[Na+]", [0]),
        ]
        for reference, candidate, indices in cases:
            with self.subTest(candidate=candidate):
                proof = compile_reference(block(reference), indices).compare_details(
                    block(candidate)
                )
                self.assertNotEqual(proof["match_status"], "matched")
                self.assertEqual(proof["variable_atom_indices"], [])
                self.assertEqual(proof["attachment_mapping"], [])

    def test_ambiguity_or_search_budget_never_leaks_an_arbitrary_embedding(self):
        matcher = compile_reference(block("CC"), [0])
        result = matcher.compare_details(block("CCC"))
        self.assertEqual(result["match_status"], "ambiguous")
        self.assertEqual(result["variable_atom_indices"], [])
        with patch("patent_sar_extractor.core.sar.graphs.MAX_SEARCH_STATES", 1):
            result = compile_reference(block("COc1ncccc1"), [0]).compare_details(
                block("CCOc1ncccc1")
            )
        self.assertEqual(result["match_status"], "ambiguous")
        self.assertEqual(result["attachment_mapping"], [])

    def test_acyclic_scaffolds_use_exact_full_graph_not_one_empty_bucket(self):
        first, repeated, changed = [
            graph_description(block(value)) for value in ("CCO", "OCC", "CCN")
        ]
        self.assertEqual(first["scaffold_id"], repeated["scaffold_id"])
        self.assertNotEqual(first["scaffold_id"], changed["scaffold_id"])
        self.assertIn("acyclic_full_graph_not_shared_core", first["reasons"])
        stereo = graph_description(block("CC(F)Cl"))
        self.assertIn("stereochemistry_unassigned", stereo["reasons"])

    def test_confirmed_core_allows_multiple_external_branches_but_not_core_changes(
        self,
    ):
        reference = block("COc1ccc(Cl)cc1")
        core = compile_core(reference, [2, 3, 4, 5, 7, 8])
        self.assertTrue(core.membership(reference)["assigned"])
        self.assertTrue(core.membership(block("CCOc1ccc(Br)cc1"))["assigned"])
        self.assertFalse(core.membership(block("CCOc1ccncc1"))["assigned"])
        self.assertFalse(core.membership(block("CCOc1ccc(Br)cc1.[Na+]"))["assigned"])
        self.assertIn("*:", core.smiles)

    def test_confirmed_core_preserves_fixed_stereo_and_spectator_salts(self):
        core = compile_core(block("C[C@H](F)COC"), [0, 1, 2, 3, 4])
        self.assertTrue(core.membership(block("C[C@H](F)COCC"))["assigned"])
        self.assertFalse(core.membership(block("C[C@@H](F)COCC"))["assigned"])
        self.assertFalse(core.membership(block("CC(F)COCC"))["assigned"])
        salted = compile_core(block("COc1ccc(Cl)cc1.[Na+]"), [2, 3, 4, 5, 7, 8])
        self.assertTrue(salted.membership(block("CCOc1ccc(Br)cc1.[Na+]"))["assigned"])
        self.assertFalse(salted.membership(block("CCOc1ccc(Br)cc1.[K+]"))["assigned"])

    def test_whole_graph_core_keeps_components_without_relaxing_variable_selection(
        self,
    ):
        reference = block("CCO.[Na+]")
        core = compile_core(reference, [0, 1, 2, 3])
        self.assertTrue(core.membership(block("[Na+].OCC"))["assigned"])
        self.assertFalse(core.membership(block("CCO.[K+]"))["assigned"])
        self.assertFalse(core.membership(block("CCO"))["assigned"])
        with self.assertRaises(ValueError):
            validate_region(reference, [0, 1, 2, 3])
        self.assertEqual(Chem.MolToSmiles(Chem.MolFromSmiles(core.smiles)), "CCO.[Na+]")


if __name__ == "__main__":
    unittest.main()
