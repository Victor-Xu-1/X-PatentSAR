"""A connected three-port change is not several disconnected substitutions."""

import unittest
from itertools import combinations
from random import Random

from rdkit import Chem
from test_sar_discovery import source

from patent_sar_extractor.core.sar.cut_topology import boundary_regions
from patent_sar_extractor.core.sar.discovery import discover_sites
from patent_sar_extractor.core.sar.matching import compile_reference
from patent_sar_extractor.core.sar.study_graphs import cut_identity, reference_cut


class ThreeportTests(unittest.TestCase):
    def test_bounded_seeded_graphs_have_exact_cut_coverage_without_duplicates(self):
        random = Random(731)
        for count in range(3, 11):
            for case in range(8):
                editable = Chem.RWMol()
                for _ in range(count):
                    editable.AddAtom(Chem.Atom(6))
                for node in range(1, count):
                    editable.AddBond(node - 1, node, Chem.BondType.SINGLE)
                for _ in range(case):
                    left, right = random.sample(range(count), 2)
                    if editable.GetBondBetweenAtoms(left, right) is None and all(
                        editable.GetAtomWithIdx(index).GetDegree() < 4
                        for index in (left, right)
                    ):
                        editable.AddBond(left, right, Chem.BondType.SINGLE)
                mol = editable.GetMol()
                Chem.SanitizeMol(mol)
                expected = set()
                for size in (1, 2, 3):
                    for cuts in combinations(range(mol.GetNumBonds()), size):
                        fragmented = Chem.FragmentOnBonds(mol, list(cuts))
                        for component in Chem.GetMolFrags(fragmented):
                            originals = [index for index in component if index < count]
                            # An internal removed ring bond contributes TWO
                            # dummies, not two boundary ports. Every supplied
                            # edge must cross this exact original component.
                            if (
                                originals
                                and len(component) - len(originals) == size
                                and all(
                                    (
                                        mol.GetBondWithIdx(edge).GetBeginAtomIdx()
                                        in originals
                                    )
                                    != (
                                        mol.GetBondWithIdx(edge).GetEndAtomIdx()
                                        in originals
                                    )
                                    for edge in cuts
                                )
                            ):
                                expected.add(
                                    (cuts, sum(1 << index for index in originals))
                                )
                with self.subTest(count=count, case=case):
                    actual = list(boundary_regions(mol, lambda: None))
                    self.assertEqual(len(actual), len(set(actual)))
                    self.assertEqual(set(actual), expected)

    def test_three_cut_partitions_equal_independent_rdkit_component_oracle(self):
        for raw in (
            "CCOCCN",
            "CC(C)CCN",
            "NC1COCC1F",
            "FC1CC2CCC1C2N",
            "NC1C2CC1CC2F",
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
                for size in (1, 2, 3):
                    for cuts in combinations(eligible, size):
                        fragmented = Chem.FragmentOnBonds(mol, list(cuts))
                        for component in Chem.GetMolFrags(fragmented):
                            atoms = tuple(index for index in component if index < count)
                            if (
                                atoms
                                and len(component) - len(atoms) == size
                                and all(
                                    (
                                        mol.GetBondWithIdx(edge).GetBeginAtomIdx()
                                        in atoms
                                    )
                                    != (
                                        mol.GetBondWithIdx(edge).GetEndAtomIdx()
                                        in atoms
                                    )
                                    for edge in cuts
                                )
                            ):
                                expected.add((cuts, sum(1 << index for index in atoms)))
                actual = list(boundary_regions(mol, lambda: None))
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), expected)

    def test_auto_discovers_three_arm_and_bridged_region_in_both_directions(self):
        for smiles in (
            ("COC(c1ccccc1)Nc1ncccc1", "CON(c1ccccc1)Nc1ncccc1"),
            ("FC1CC2CCC1C2N", "FC1CN2CCC1C2N"),
        ):
            with self.subTest(smiles=smiles):
                rows = [source(str(index + 1), raw) for index, raw in enumerate(smiles)]
                plans, coverage = discover_sites(
                    rows, {"id": "controlled", "revision": 1}
                )
                proved = set()
                indexed = {row["id"]: row for row in rows}
                for plan in plans:
                    region = plan["region"]
                    if region["attachment_count"] != 3:
                        continue
                    reference = indexed[region["molecule_id"]]["molfile"]
                    matcher = compile_reference(reference, region["atom_indices"])
                    for mid in plan["candidate_ids"]:
                        candidate = indexed[mid]["molfile"]
                        proof = matcher.compare_details(candidate)
                        if proof["match_status"] != "matched":
                            continue
                        self.assertEqual(len(proof["attachment_mapping"]), 3)
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
                        proved.add((region["molecule_id"], mid))
                self.assertEqual(proved, {("1", "2"), ("2", "1")})
                self.assertEqual(coverage["max_cut_bonds"], 3)
                self.assertEqual(
                    discover_sites(
                        list(reversed(rows)), {"id": "controlled", "revision": 1}
                    ),
                    (plans, coverage),
                )

    def test_three_port_changes_still_reject_fixed_atoms_and_spectators(self):
        reference = source("1", "COC(c1ccccc1)Nc1ncccc1")
        matcher = compile_reference(reference["molfile"], [2])
        self.assertEqual(
            matcher.compare(source("2", "CON(c1ccccc1)Nc1ncccc1")["molfile"])[
                "match_status"
            ],
            "matched",
        )
        for raw in (
            "CON(c1ccccc1)Nc1cccnc1",
            "C[18O]N(c1ccccc1)Nc1ncccc1",
            "CON(c1ccccc1)Nc1[nH+]cccc1",
            "CON(c1ccccc1)Nc1ncccc1.[Na+]",
            "CCON(c1ccccc1)Nc1ncccc1",
        ):
            with self.subTest(raw=raw):
                self.assertNotEqual(
                    matcher.compare(source("3", raw)["molfile"])["match_status"],
                    "matched",
                )

    def test_three_port_proof_preserves_fixed_stereo_under_atom_reordering(self):
        reference = source("1", "COC(c1ccccc1)N[C@H](F)c1ncccc1")
        matcher = compile_reference(reference["molfile"], [2])
        candidate = Chem.MolFromSmiles("CON(c1ccccc1)N[C@H](F)c1ncccc1")
        reordered = Chem.RenumberAtoms(
            candidate, list(reversed(range(candidate.GetNumAtoms())))
        )
        self.assertEqual(
            matcher.compare(Chem.MolToMolBlock(reordered))["match_status"], "matched"
        )
        self.assertNotEqual(
            matcher.compare(source("2", "CON(c1ccccc1)N[C@@H](F)c1ncccc1")["molfile"])[
                "match_status"
            ],
            "matched",
        )
