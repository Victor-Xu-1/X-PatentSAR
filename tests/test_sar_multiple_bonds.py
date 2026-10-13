"""Multiple-bond candidate boundaries never replace full fixed-graph proof."""

import unittest
from itertools import combinations

from rdkit import Chem
from test_sar_discovery import source

from patent_sar_extractor.core.sar.cut_topology import boundary_regions
from patent_sar_extractor.core.sar.discovery import discover_sites
from patent_sar_extractor.core.sar.matching import compile_reference
from patent_sar_extractor.core.sar.study_graphs import cut_identity, reference_cut
from patent_sar_extractor.web.sar.assets import digest


class MultipleBondTests(unittest.TestCase):
    def test_minimal_terminal_change_is_discovered_in_both_directions(self):
        for left, right in (
            ("O=C1CCNCC1", "S=C1CCNCC1"),
            ("O=c1cccc[nH]1", "S=c1cccc[nH]1"),
            ("COc1ccc(C(=O)NC)cc1", "COc1ccc(C(=S)NC)cc1"),
            ("COc1ccc(C#N)cc1", "COc1ccc(C#C)cc1"),
            ("C[C@H](F)c1ccc(C(=O)NC)cc1", "C[C@H](F)c1ccc(C(=S)NC)cc1"),
        ):
            for reorder in (False, True):
                with self.subTest(left=left, right=right, reorder=reorder):
                    rows = [source("A", left), source("B", right)]
                    if reorder:
                        for row in rows:
                            mol = Chem.MolFromMolBlock(row["molfile"])
                            row["molfile"] = Chem.MolToMolBlock(
                                Chem.RenumberAtoms(
                                    mol, list(reversed(range(mol.GetNumAtoms())))
                                )
                            )
                            row["graph_sha256"] = digest(row["molfile"])
                    by_id = {row["id"]: row for row in rows}
                    plans, _ = discover_sites(
                        rows, {"id": "independent", "revision": 1}
                    )
                    found = set()
                    for plan in plans:
                        region = plan["region"]
                        if len(region["atom_indices"]) != 1:
                            continue
                        reference = by_id[region["molecule_id"]]["molfile"]
                        matcher = compile_reference(reference, region["atom_indices"])
                        for mid in plan["candidate_ids"]:
                            candidate = by_id[mid]["molfile"]
                            proof = matcher.compare_details(candidate)
                            if proof["match_status"] != "matched":
                                continue
                            self.assertEqual(len(proof["variable_atom_indices"]), 1)
                            self.assertEqual(
                                cut_identity(
                                    candidate,
                                    proof["variable_atom_indices"],
                                    proof["attachment_mapping"],
                                )["fixed_background_sha256"],
                                reference_cut(reference, region["atom_indices"])[
                                    "fixed_background_sha256"
                                ],
                            )
                            found.add((region["molecule_id"], mid))
                    self.assertEqual(found, {("A", "B"), ("B", "A")})

    def test_mixed_bond_topology_equals_independent_full_cut_oracle(self):
        for raw in (
            "O=C1CCNCC1",
            "O=c1cccc[nH]1",
            "COc1ccc(C#N)cc1",
            "CC(=O)NCC(=S)N",
            "O=C1C=CC(=O)CC1",
            "CC/C=C/CC#N",
            "O=C1CCNCC1.[Cl-]",
        ):
            with self.subTest(raw=raw):
                mol = Chem.MolFromSmiles(raw)
                count, expected = mol.GetNumAtoms(), set()
                for size in (1, 2, 3):
                    for cuts in combinations(range(mol.GetNumBonds()), size):
                        fragmented = Chem.FragmentOnBonds(mol, list(cuts))
                        for component in Chem.GetMolFrags(fragmented):
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

    def test_fixed_changes_and_stereogenic_boundary_are_still_refused(self):
        left = source("A", "C[C@H](F)c1ccc(C(=O)NC)cc1")
        selected = [8]
        matcher = compile_reference(left["molfile"], selected)
        for right in (
            "C[C@@H](F)c1ccc(C(=S)NC)cc1",
            "[13CH3][C@H](F)c1ccc(C(=S)NC)cc1",
            "C[C@H](F)c1ccc(C(=S)[NH2+]C)cc1",
            "C[C@H](F)c1ccc(C(=S)NC)cc1.[Cl-]",
            "C[C@H](F)c1ccc(C(=NC)NC)cc1",
        ):
            with self.subTest(right=right):
                self.assertNotEqual(
                    matcher.compare(source("B", right)["molfile"])["match_status"],
                    "matched",
                )
        stereogenic = source("C", "CC/C=C/CCc1ccccc1")
        with self.assertRaisesRegex(ValueError, "unsupported_boundary_bond_stereo"):
            compile_reference(stereogenic["molfile"], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
