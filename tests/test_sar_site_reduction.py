"""Index-only overlap cannot drop a valid broader comparison."""

import unittest
from itertools import permutations

from rdkit import Chem
from test_sar_discovery import source

from patent_sar_extractor.core.sar.graphs import FixedAtoms, fixed_mappings, graph
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
    def test_prepared_induced_embeddings_equal_small_complete_bijection_oracle(self):
        for left, right, selected in (
            ("CCOC", "CCSC", [2]),
            ("NC1CCC1F", "NC1CCC1Cl", [5]),
            ("CC1CO1", "CC1CCO1", [0]),
            ("CCO.[Na+]", "CCC.[Na+]", [2]),
            ("CC1CCC1", "C1CCCCC1", [0]),
        ):
            with self.subTest(left=left, right=right):
                reference, candidate = (
                    graph(Chem.MolFromSmiles(left)),
                    graph(Chem.MolFromSmiles(right)),
                )
                variable = frozenset(selected)
                fixed = sorted(set(range(len(reference.atoms))) - variable)
                expected = set()
                for images in permutations(range(len(candidate.atoms)), len(fixed)):
                    mapping = dict(zip(fixed, images))
                    if all(
                        reference.atoms[source] == candidate.atoms[target]
                        for source, target in mapping.items()
                    ) and all(
                        reference.adjacency[source].get(other)
                        == candidate.adjacency[target].get(mapping[other])
                        for source, target in mapping.items()
                        for other in fixed
                    ):
                        expected.add(tuple(sorted(mapping.items())))
                actual = {
                    tuple(sorted(mapping.items()))
                    for mapping in fixed_mappings(
                        reference,
                        candidate,
                        variable,
                        prepared=FixedAtoms(reference, variable),
                    )
                }
                self.assertEqual(actual, expected)

    def test_prepared_order_is_exact_and_its_cache_is_bounded(self):
        reference = graph(Chem.MolFromSmiles("COc1ccccc1Cl"))
        selected = frozenset({5})
        prepared = FixedAtoms(reference, selected)
        for offset in range(12):
            domains = {
                index: tuple(range((index + offset) % 12 + 1))
                for index in prepared.nodes
            }
            expected, unplaced = [], set(prepared.fixed)
            while unplaced:
                node = min(
                    unplaced,
                    key=lambda index: (
                        -sum(other in expected for other in reference.adjacency[index]),
                        len(domains[index]),
                        -len(reference.adjacency[index]),
                        index,
                    ),
                )
                expected.append(node)
                unplaced.remove(node)
            self.assertEqual(prepared.order(domains), tuple(expected))
            self.assertEqual(prepared.order(domains), tuple(expected))
            self.assertLessEqual(len(prepared._orders), 8)
        with self.assertRaisesRegex(ValueError, "fixed_preparation_identity"):
            list(
                fixed_mappings(reference, reference, frozenset({4}), prepared=prepared)
            )

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
