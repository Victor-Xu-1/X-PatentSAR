"""Partial aromatic regions stay labelled graphs, not invented full molecules."""

import unittest
from collections import Counter
from itertools import combinations

from rdkit import Chem, rdBase
from test_sar_discovery import source
from test_sar_graph import prepared

from patent_sar_extractor.core.sar.cut_topology import boundary_regions
from patent_sar_extractor.core.sar.discovery import discover_sites
from patent_sar_extractor.core.sar.drawing import draw_fragment
from patent_sar_extractor.core.sar.fragment_graphs import graph_notation
from patent_sar_extractor.core.sar.matching import compile_reference
from patent_sar_extractor.core.sar.site_cuts import candidate_cuts
from patent_sar_extractor.core.sar.study_graphs import cut_identity, reference_cut


class AromaticTests(unittest.TestCase):
    def test_index_keys_equal_independent_complete_fragment_components(self):
        for raw in (
            "COc1ccccc1Cl",
            "COc1ccc2ccccc2c1Cl",
            "c1ccccc1Oc1ccccc1Cl",
            "NC1COCC1F",
            "FC1CC2CCC1C2N.[Na+]",
        ):
            with self.subTest(raw=raw), rdBase.BlockLogs():
                mol = Chem.MolFromSmiles(raw)
                count = mol.GetNumAtoms()
                cuts = list(
                    candidate_cuts(
                        mol,
                        lambda: None,
                        Counter(),
                        max_variable=32,
                        max_fraction=0.4,
                        min_fixed=6,
                    )
                )
                self.assertTrue(cuts)
                for actual, selection, port_count in cuts:
                    selected = set(selection)
                    boundary = [
                        bond.GetIdx()
                        for bond in mol.GetBonds()
                        if (bond.GetBeginAtomIdx() in selected)
                        != (bond.GetEndAtomIdx() in selected)
                    ]
                    self.assertEqual(len(boundary), port_count)
                    fractured = Chem.FragmentOnBonds(
                        mol,
                        boundary,
                        dummyLabels=[(0, 0)] * len(boundary),
                    )
                    for index in range(count, fractured.GetNumAtoms()):
                        fractured.GetAtomWithIdx(index).SetAtomMapNum(1)
                    variable = next(
                        component
                        for component in Chem.GetMolFrags(fractured)
                        if {index for index in component if index < count} == selected
                    )
                    fixed = sorted(set(range(fractured.GetNumAtoms())) - set(variable))
                    if any(
                        mol.GetBondWithIdx(edge).GetIsAromatic() for edge in boundary
                    ):
                        expected = "aromatic-graph-index-v1:" + graph_notation(
                            fractured, fixed
                        )
                    else:
                        fragment = Chem.MolFragmentToSmiles(
                            fractured,
                            atomsToUse=fixed,
                            canonical=True,
                            isomericSmiles=True,
                        )
                        expected = Chem.MolToSmiles(
                            Chem.MolFromSmiles(fragment), isomericSmiles=True
                        )
                    self.assertEqual(actual, expected)

    def test_aromatic_and_ring_block_partitions_equal_independent_components(self):
        for raw in (
            "COc1ccccc1Cl",
            "COc1ccncc1Cl",
            "COc1ccc2ccccc2c1Cl",
            "c1ccccc1Oc1ccccc1Cl",
            "C1CC2(C1)CCC2",
            "N1CCCCC1c1ccccc1",
        ):
            with self.subTest(raw=raw):
                mol = Chem.MolFromSmiles(raw)
                count = mol.GetNumAtoms()
                eligible = [
                    bond.GetIdx()
                    for bond in mol.GetBonds()
                    if bond.GetBondType() == Chem.BondType.SINGLE
                    or bond.GetIsAromatic()
                ]
                expected = set()
                for size in (1, 2, 3):
                    for cuts in combinations(eligible, size):
                        fractured = Chem.FragmentOnBonds(mol, list(cuts))
                        for component in Chem.GetMolFrags(fractured):
                            originals = {index for index in component if index < count}
                            if originals and all(
                                (
                                    mol.GetBondWithIdx(edge).GetBeginAtomIdx()
                                    in originals
                                )
                                != (
                                    mol.GetBondWithIdx(edge).GetEndAtomIdx()
                                    in originals
                                )
                                for edge in cuts
                            ):
                                expected.add(
                                    (cuts, sum(1 << index for index in originals))
                                )
                actual = list(boundary_regions(mol, lambda: None))
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)

    def test_single_ring_atom_change_preserves_fixed_graph_and_derivative_identity(
        self,
    ):
        left, right = prepared("COc1ccccc1Cl"), prepared("COc1ccncc1Cl")
        proof = compile_reference(left, [5]).compare_details(right)
        self.assertEqual(proof["match_status"], "matched")
        reference = reference_cut(left, [5])
        changed = cut_identity(
            right, proof["variable_atom_indices"], proof["attachment_mapping"]
        )
        self.assertIsNone(reference["smiles"])
        self.assertIsNone(changed["smiles"])
        self.assertTrue(reference["graph_smiles"])
        self.assertEqual(
            reference["fixed_background_sha256"], changed["fixed_background_sha256"]
        )
        self.assertNotEqual(reference["id"], changed["id"])
        for fragment in (reference, changed):
            self.assertIn(
                "<svg", draw_fragment(None, graph_smiles=fragment["graph_smiles"])
            )

    def test_aromatic_graph_identity_survives_original_atom_reordering(self):
        original = Chem.MolFromSmiles("COc1ccccc1Cl")
        expected = reference_cut(Chem.MolToMolBlock(original), [5])
        order = list(reversed(range(original.GetNumAtoms())))
        reordered = Chem.RenumberAtoms(original, order)
        changed = cut_identity(
            Chem.MolToMolBlock(reordered),
            [order.index(5)],
            [[4, order.index(4)], [6, order.index(6)]],
        )
        self.assertEqual(changed, expected)

    def test_auto_discovers_partial_aromatic_change_without_whole_ring_relaxation(self):
        rows = [source("1", "COc1ccccc1Cl"), source("2", "COc1ccncc1Cl")]
        plans, coverage = discover_sites(rows, {"id": "controlled", "revision": 1})
        proved = set()
        by_id = {row["id"]: row for row in rows}
        for plan in plans:
            region = plan["region"]
            if len(region["atom_indices"]) != 1:
                continue
            matcher = compile_reference(
                by_id[region["molecule_id"]]["molfile"], region["atom_indices"]
            )
            for candidate in plan["candidate_ids"]:
                if (
                    matcher.compare(by_id[candidate]["molfile"])["match_status"]
                    == "matched"
                ):
                    proved.add((region["molecule_id"], candidate))
        self.assertEqual(proved, {("1", "2"), ("2", "1")})
        self.assertTrue(coverage["aromatic_boundaries"])

    def test_other_ring_positions_charge_isotope_and_components_stay_fixed(self):
        matcher = compile_reference(prepared("COc1ccccc1Cl"), [5])
        for value in (
            "COc1cnccc1Cl",
            "C[18O]c1ccncc1Cl",
            "COc1ccncc1Br",
            "COc1cc[nH+]cc1Cl.[Cl-]",
            "COc1ccncc1Cl.[Na+]",
        ):
            with self.subTest(value=value):
                self.assertNotEqual(
                    matcher.compare(prepared(value))["match_status"], "matched"
                )
