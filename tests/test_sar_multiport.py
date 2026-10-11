"""One connected modification with unchanged fixed anchors, not a relaxed MCS."""

import unittest
from itertools import combinations
from unittest.mock import patch

from rdkit import Chem
from test_sar_discovery import source
from test_sar_graph import prepared

from patent_sar_extractor.core.sar.cut_topology import boundary_regions
from patent_sar_extractor.core.sar.discovery import discover_sites
from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.matching import compile_reference
from patent_sar_extractor.core.sar.study_graphs import cut_identity, reference_cut


class MultiportTests(unittest.TestCase):
    def test_boundary_double_bond_carrier_is_preserved_after_linker_extension(self):
        matcher = compile_reference(prepared("Cl/C=C/COc1ccccc1F"), [3])
        self.assertEqual(
            matcher.compare(prepared("Cl/C=C/CCOc1ccccc1F"))["match_status"], "matched"
        )
        self.assertEqual(
            matcher.compare(prepared("Cl/C=C\\CCOc1ccccc1F"))["match_status"],
            "not_matched",
        )

    def test_two_cut_topology_equals_independent_rdkit_component_oracle(self):
        for raw in (
            "CCOCCN",
            "CC(C)CCN",
            "NC1COCC1F",
            "FC1CC2CCC1C2N",
            "CC1(CCCO1)N",
            "COCC.CCN",
            "COc1ccccc1F",
        ):
            with self.subTest(raw=raw):
                mol = Chem.MolFromSmiles(raw)
                count = mol.GetNumAtoms()
                eligible = [
                    bond.GetIdx()
                    for bond in mol.GetBonds()
                    if bond.GetBondType() == Chem.BondType.SINGLE
                    and not bond.GetIsAromatic()
                ]
                expected = set()
                for size in (1, 2):
                    for cuts in combinations(eligible, size):
                        cut = Chem.FragmentOnBonds(mol, list(cuts))
                        for component in Chem.GetMolFrags(cut):
                            atoms = tuple(index for index in component if index < count)
                            if atoms and len(component) - len(atoms) == size:
                                expected.add((cuts, sum(1 << index for index in atoms)))
                self.assertEqual(
                    {
                        item
                        for item in boundary_regions(mol, lambda: None)
                        if len(item[0]) <= 2
                        and all(
                            not mol.GetBondWithIdx(edge).GetIsAromatic()
                            for edge in item[0]
                        )
                    },
                    expected,
                )

    def test_boundary_search_budget_refuses_without_publishing_partial_sites(self):
        rows = [source("1", "n1ccccc1COc1ccccc1F"), source("2", "n1ccccc1CCOc1ccccc1F")]
        with (
            patch("patent_sar_extractor.core.sar.discovery.MAX_BOUNDARIES", 1),
            self.assertRaises(SARInputError) as refusal,
        ):
            discover_sites(rows, {"id": "dataset", "revision": 1})
        self.assertEqual(refusal.exception.code, "study_discovery_boundary_limit")

    def test_one_atom_linker_can_extend_between_the_same_two_fixed_anchors(self):
        reference = prepared("n1ccccc1COc1ccccc1F")
        matcher = compile_reference(reference, [6])
        for changed in ("n1ccccc1CCOc1ccccc1F", "n1ccccc1C(C)COc1ccccc1F"):
            with self.subTest(changed=changed):
                block = prepared(changed)
                proof = matcher.compare_details(block)
                self.assertEqual(proof["match_status"], "matched", proof)
                self.assertEqual(len(proof["attachment_mapping"]), 2)
                self.assertGreater(len(proof["variable_atom_indices"]), 1)
                fragment = cut_identity(
                    block, proof["variable_atom_indices"], proof["attachment_mapping"]
                )
                self.assertEqual(
                    fragment["fixed_background_sha256"],
                    reference_cut(reference, [6])["fixed_background_sha256"],
                )

    def test_boundary_tetrahedral_parity_uses_its_own_anchor_edge(self):
        reference = prepared("F[C@H](c1ccncc1)COc1ccccc1Cl")
        matcher = compile_reference(reference, [8])
        candidate = Chem.MolFromSmiles("F[C@H](c1ccncc1)CCOc1ccccc1Cl")
        for order in (
            list(range(candidate.GetNumAtoms())),
            list(reversed(range(candidate.GetNumAtoms()))),
        ):
            with self.subTest(order=order):
                mol = Chem.RenumberAtoms(candidate, order)
                for block in (
                    Chem.MolToMolBlock(mol),
                    prepared(Chem.MolToSmiles(mol, canonical=False)),
                ):
                    proof = matcher.compare_details(block)
                    self.assertEqual(proof["match_status"], "matched", proof)
                mol.GetAtomWithIdx(order.index(1)).InvertChirality()
                self.assertNotEqual(
                    matcher.compare(Chem.MolToMolBlock(mol))["match_status"], "matched"
                )

    def test_linker_changes_cannot_alter_fixed_stereo_isotope_charge_or_ports(self):
        matcher = compile_reference(prepared("F[C@H](c1ccncc1)COc1ccccc1Cl"), [8])
        for candidate in (
            "F[C@@H](c1ccncc1)CCOc1ccccc1Cl",
            "FC(c1ccncc1)CCOc1ccccc1Cl",
            "F[C@H](c1cc[nH+]cc1)CCOc1ccccc1Cl",
            "F[C@H](c1ccncc1)CC[18O]c1ccccc1Cl",
            "F[C@H](c1ccncc1)CCOc1cccc(Cl)c1",
            "F[C@H](c1ccncc1)CCOc1ccccc1Cl.[Na+]",
        ):
            with self.subTest(candidate=candidate):
                self.assertNotEqual(
                    matcher.compare(prepared(candidate))["match_status"], "matched"
                )

    def test_nonaromatic_ring_segment_extension_keeps_the_whole_fixed_background(self):
        reference = prepared("NC1COCC1F")
        changed = prepared("NC1CCOCC1F")
        proof = compile_reference(reference, [2]).compare_details(changed)
        self.assertEqual(proof["match_status"], "matched", proof)
        self.assertEqual(proof["variable_atom_indices"], [2, 3])
        self.assertEqual(
            cut_identity(
                changed, proof["variable_atom_indices"], proof["attachment_mapping"]
            )["fixed_background_sha256"],
            reference_cut(reference, [2])["fixed_background_sha256"],
        )

    def test_ambiguous_two_neighbours_at_one_fixed_stereo_anchor_remain_refused(self):
        proof = compile_reference(
            prepared("F[C@]1(Cl)CCCO1"), [3, 4, 5, 6]
        ).compare_details(prepared("F[C@]1(Cl)CCCCO1"))
        self.assertEqual(proof["match_status"], "ineligible")
        self.assertEqual(proof["variable_atom_indices"], [])

    def test_auto_discovers_two_ended_linkers_and_ring_segments_in_both_directions(
        self,
    ):
        for smiles in (
            ("n1ccccc1COc1ccccc1F", "n1ccccc1CCOc1ccccc1F"),
            ("NC1COCC1F", "NC1CCOCC1F"),
        ):
            with self.subTest(smiles=smiles):
                rows = [
                    source(str(index + 1), value) for index, value in enumerate(smiles)
                ]
                plans, coverage = discover_sites(rows, {"id": "dataset", "revision": 1})
                proved = set()
                by_id = {row["id"]: row for row in rows}
                for plan in plans:
                    region = plan["region"]
                    if region["attachment_count"] != 2:
                        continue
                    matcher = compile_reference(
                        by_id[region["molecule_id"]]["molfile"], region["atom_indices"]
                    )
                    for mid in plan["candidate_ids"]:
                        if (
                            matcher.compare(by_id[mid]["molfile"])["match_status"]
                            == "matched"
                        ):
                            proved.add((region["molecule_id"], mid))
                self.assertEqual(proved, {("1", "2"), ("2", "1")})
                self.assertEqual(coverage["max_cut_bonds"], 3)
                self.assertEqual(
                    discover_sites(
                        list(reversed(rows)), {"id": "dataset", "revision": 1}
                    ),
                    (plans, coverage),
                )
