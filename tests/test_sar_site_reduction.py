"""Index-only overlap cannot drop a valid broader comparison."""

import unittest

from rdkit import Chem
from test_sar_discovery import source

from patent_sar_extractor.core.sar.matching import compile_reference
from patent_sar_extractor.core.sar.prepared_graphs import GraphPool
from patent_sar_extractor.core.sar.site_reduction import compact_proved_sites


def plan(identifier, atoms):
    return {
        "region": {
            "id": identifier,
            "molecule_id": "1",
            "atom_indices": atoms,
            "hydrogen_anchor": None,
        },
        "candidate_ids": ["2"],
    }


class SiteReductionTests(unittest.TestCase):
    def test_only_a_complete_stricter_match_can_remove_a_nested_duplicate(self):
        rows = [source("1", "COc1ccccc1Cl"), source("2", "COc1ccncc1Cl")]
        plans = [plan("small", [5]), plan("large", [4, 5, 6])]
        kept, removed = compact_proved_sites(plans, rows, GraphPool(), lambda: None)
        self.assertEqual(
            ([item["region"]["id"] for item in kept], removed), (["small"], 1)
        )

    def test_failed_stricter_region_cannot_remove_a_valid_broader_region(self):
        rows = [source("1", "COc1ccccc1Cl"), source("2", "COc1cnccc1Cl")]
        plans = [plan("small", [5]), plan("large", [4, 5, 6])]
        self.assertEqual(
            compile_reference(rows[0]["molfile"], [4, 5, 6]).compare(
                rows[1]["molfile"]
            )["match_status"],
            "matched",
        )
        self.assertEqual(
            compact_proved_sites(plans, rows, GraphPool(), lambda: None), (plans, 0)
        )

    def test_pool_preserves_exact_original_atom_order_and_normal_proof(self):
        rows = [source("1", "COc1ccccc1Cl"), source("2", "COc1ccncc1Cl")]
        pool = GraphPool()
        original = rows[1]["molfile"]
        mol = Chem.MolFromMolBlock(original)
        reversed_mol = Chem.RenumberAtoms(mol, list(reversed(range(mol.GetNumAtoms()))))
        reversed_block = Chem.MolToMolBlock(reversed_mol)
        cached = compile_reference(rows[0]["molfile"], [5], pool=pool)
        plain = compile_reference(rows[0]["molfile"], [5])
        for block in (original, reversed_block, original):
            self.assertEqual(
                cached.compare_details(block), plain.compare_details(block)
            )
        self.assertIsNot(pool.read(original), pool.read(reversed_block))
