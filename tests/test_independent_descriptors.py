"""Five real calculations do not depend on the LogS neural model boundary."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class IndependentDescriptorTests(unittest.TestCase):
    def test_exact_five_metrics_match_rdkit_without_model_call(self):
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors

        from patent_sar_extractor.web.descriptor_fields import compute_descriptors

        with patch(
            "patent_sar_extractor.web.analysis.AnalysisService.admet",
            side_effect=AssertionError("No model"),
        ):
            values = compute_descriptors("CCO")
        self.assertEqual(
            [value.key for value in values],
            [
                "molecular_weight",
                "logP",
                "tpsa",
                "hydrogen_bond_donors",
                "hydrogen_bond_acceptors",
            ],
        )
        molecule = Chem.MolFromSmiles("CCO")
        expected = (
            Descriptors.MolWt(molecule),
            Crippen.MolLogP(molecule),
            rdMolDescriptors.CalcTPSA(molecule),
            Lipinski.NumHDonors(molecule),
            Lipinski.NumHAcceptors(molecule),
        )
        for actual, value in zip(values, expected):
            self.assertAlmostEqual(actual.value, value, places=8)
            self.assertEqual(actual.kind, "descriptor")

    def test_invalid_graph_has_no_fabricated_values(self):
        from patent_sar_extractor.web.descriptor_fields import compute_descriptors
        from patent_sar_extractor.web.errors import WebError

        with self.assertRaises(WebError):
            compute_descriptors("C1CC")

    def test_isotopes_and_fragments_are_not_removed(self):
        from patent_sar_extractor.web.descriptor_fields import compute_descriptors

        ordinary = compute_descriptors("CO")[0].value
        isotope = compute_descriptors("[13CH3]O")[0].value
        salt = compute_descriptors("CO.[Na+]")[0].value
        self.assertGreater(isotope, ordinary)
        self.assertGreater(salt, ordinary)


if __name__ == "__main__":
    unittest.main()
