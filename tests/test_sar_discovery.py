"""Same fixed-background authority, multiple centres and refusal boundaries."""

import unittest
from typing import ClassVar

from rdkit import Chem

from patent_sar_extractor.core.sar.discovery import discover_sites
from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.matching import compile_reference
from patent_sar_extractor.web.sar.assets import digest


def source(identifier, smiles):
    molfile = Chem.MolToMolBlock(Chem.MolFromSmiles(smiles))
    return {
        "id": identifier,
        "label": identifier,
        "eligible": True,
        "molfile": molfile,
        "graph_sha256": digest(molfile),
    }


class DiscoveryTests(unittest.TestCase):
    dataset: ClassVar[dict] = {"id": "dataset", "revision": 1}

    def test_multiple_centres_directions_and_exact_native_proof(self):
        rows = [
            source("1", "COc1ccc(Cl)cc1"),
            source("2", "CCOc1ccc(Cl)cc1"),
            source("3", "COc1ccc(Br)cc1"),
            source("4", "CCCOc1ccc(Cl)cc1"),
        ]
        plans, coverage = discover_sites(rows, self.dataset)
        self.assertEqual(
            {plan["region"]["molecule_id"] for plan in plans}, {"1", "2", "3", "4"}
        )
        self.assertGreater(
            sum(plan["region"]["molecule_id"] == "1" for plan in plans), 1
        )
        indexed = {row["id"]: row for row in rows}
        proved = set()
        for plan in plans:
            region = plan["region"]
            matcher = compile_reference(
                indexed[region["molecule_id"]]["molfile"],
                region["atom_indices"],
                hydrogen_anchor=region.get("hydrogen_anchor"),
            )
            for mid in plan["candidate_ids"]:
                result = matcher.compare_details(indexed[mid]["molfile"])
                if result["match_status"] == "matched":
                    proved.add(tuple(sorted((region["molecule_id"], mid))))
        self.assertEqual(proved, {("1", "2"), ("1", "3"), ("1", "4"), ("2", "4")})
        self.assertEqual(coverage["candidate_sites"], len(plans))
        self.assertEqual(
            discover_sites(list(reversed(rows)), self.dataset), (plans, coverage)
        )

    def test_same_graphs_and_symmetric_sites_are_not_invented_changes(self):
        rows = [source("1", "COc1ccc(Cl)cc1"), source("2", "COc1ccc(Cl)cc1")]
        plans, _ = discover_sites(rows, self.dataset)
        self.assertEqual(plans, [])

    def test_budget_refuses_instead_of_silently_truncating(self):
        rows = [source("1", "COc1ccc(Cl)cc1"), source("2", "CCOc1ccc(Cl)cc1")]
        with self.assertRaises(SARInputError) as refusal:
            discover_sites(rows, self.dataset, pair_budget=1)
        self.assertEqual(refusal.exception.code, "study_discovery_pair_limit")

    def test_fixed_charge_isotope_stereo_and_position_do_not_pass(self):
        rows = [
            source("1", "COc1cc([C@H](F)Cl)ccc1"),
            source("2", "CCOc1cc([C@@H](F)Cl)ccc1"),
            source("3", "CCOc1cc([13CH](F)Cl)ccc1"),
            source("4", "CCOc1ccc([C@H](F)Cl)cc1"),
        ]
        matcher = compile_reference(rows[0]["molfile"], [0])
        for candidate in rows[1:]:
            self.assertNotEqual(
                matcher.compare(candidate["molfile"])["match_status"], "matched"
            )
        charge_reference = source("5", "COc1ccncc1")
        charged = source("6", "CCOc1cc[nH+]cc1")
        self.assertNotEqual(
            compile_reference(charge_reference["molfile"], [0]).compare(
                charged["molfile"]
            )["match_status"],
            "matched",
        )
        self.assertNotEqual(
            matcher.compare(source("7", "CCOc1cc([C@H](F)Cl)ccc1.[Cl-]")["molfile"])[
                "match_status"
            ],
            "matched",
        )
