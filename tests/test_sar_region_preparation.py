"""Exact original-graph preparation, with independent native RDKit oracles."""

import itertools
import unittest
from unittest.mock import patch

from rdkit import Chem
from test_sar_graph import prepared

from patent_sar_extractor.core.sar import matching, regions
from patent_sar_extractor.core.sar.graphs import graph
from patent_sar_extractor.core.sar.matching import compile_reference
from patent_sar_extractor.core.sar.prepared_graphs import GraphPool


class RegionPreparationTests(unittest.TestCase):
    def test_prepared_connectivity_and_ports_equal_native_oracles(self):
        for raw in (
            "CCOCCN",
            "CC(C)CCN",
            "NC1COCC1F",
            "Fc1ccncc1N",
            "F[C@](Cl)(Br)I",
            "Cl/C=C/CO",
            "[13CH3]CO.[Na+]",
        ):
            mol = Chem.MolFromSmiles(raw)
            source = graph(mol)
            for size in range(1, mol.GetNumAtoms() + 1):
                for values in itertools.combinations(range(mol.GetNumAtoms()), size):
                    variable = frozenset(values)
                    seen, pending = set(), [min(variable)]
                    while pending:
                        index = pending.pop()
                        if index in seen:
                            continue
                        seen.add(index)
                        pending.extend(
                            other.GetIdx()
                            for other in mol.GetAtomWithIdx(index).GetNeighbors()
                            if other.GetIdx() in variable and other.GetIdx() not in seen
                        )
                    ports = {}
                    for index in sorted(variable):
                        for bond in mol.GetAtomWithIdx(index).GetBonds():
                            other = bond.GetOtherAtomIdx(index)
                            if other not in variable:
                                key = (
                                    other,
                                    (str(bond.GetBondType()), bond.GetIsAromatic()),
                                )
                                ports.setdefault(key, []).append(index)
                    with self.subTest(raw=raw, variable=values):
                        self.assertEqual(
                            regions.connected(
                                mol, variable, adjacency=source.adjacency
                            ),
                            seen == variable,
                        )
                        self.assertEqual(
                            regions.fixed_ports(
                                mol, variable, adjacency=source.adjacency
                            ),
                            ports,
                        )

    def test_full_match_uses_prepared_topology_not_repeated_native_walks(self):
        pool = GraphPool()
        reference = prepared("COc1ccc(Cl)cc1")
        positive = prepared("CCOc1ccc(Cl)cc1")
        negative = prepared("CCOc1ccc(Br)cc1")
        for block in (reference, positive, negative):
            pool.read(block)
        matcher = compile_reference(reference, [0], pool=pool)
        expected = matcher.compare_details(positive)
        self.assertEqual(expected["match_status"], "matched")
        with patch.object(
            Chem.Mol, "GetAtomWithIdx", side_effect=AssertionError("native_walk")
        ):
            self.assertEqual(matcher.compare_details(positive), expected)
            self.assertEqual(matcher.compare(negative)["match_status"], "not_matched")

    def test_indistinguishable_ports_never_choose_arbitrary_stereo_ligands(self):
        reference = Chem.MolFromSmiles("CC1(CCCO1)N")
        variable = frozenset((2, 3, 4, 5))
        source = graph(reference)
        ports = regions.fixed_ports(reference, variable, adjacency=source.adjacency)
        self.assertEqual(ports[(1, ("SINGLE", False))], [2, 5])
        mapping = {
            index: index
            for index in range(reference.GetNumAtoms())
            if index not in variable
        }
        self.assertEqual(
            regions.attachment_mapping(
                reference,
                reference,
                variable,
                variable,
                mapping,
                reference_ports=ports,
                candidate_ports=ports,
            ),
            {},
        )

    def test_shared_remaining_topology_still_checks_every_embedding_stereo(self):
        matcher = compile_reference(prepared("Cc1ccccc1"), [0])
        candidate = prepared("Oc1ccccc1")
        with (
            patch.object(matching, "preserved", wraps=matching.preserved) as stereo,
            patch.object(matching, "fixed_ports", wraps=matching.fixed_ports) as ports,
        ):
            result = matcher.compare_details(candidate)
        self.assertEqual(result["match_status"], "matched", result)
        self.assertEqual(result["variable_atom_indices"], [0])
        self.assertEqual(stereo.call_count, 2)
        self.assertEqual(ports.call_count, 1)


if __name__ == "__main__":
    unittest.main()
