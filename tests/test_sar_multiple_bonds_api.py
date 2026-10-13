"""Native multiple-bond discovery through publication, drawings and exports."""

import unittest

import test_sar_api as support
import test_sar_network_api as network_support
from test_web_support import WebFixture

from patent_sar_extractor.core.sar.discovery import discover_sites
from patent_sar_extractor.web.sar.study_models import StudyDiscovery

CSV = b"id,smiles,IC50 (nM),t_half (h),target,assay,cells,duration\nA1,O=C1CCNCC1,10,1,T,controlled,C,1h\nA2,S=C1CCNCC1,1,3,T,controlled,C,1h\nA3,O=C1CCOCC1,,4,T,controlled,C,1h\nB1,COc1ccc(C#N)cc1,20,4,T,controlled,C,1h\nB2,COc1ccc(C#C)cc1,2,6,T,controlled,C,1h\n"


class MultipleBondAPITests(WebFixture, unittest.TestCase):
    completed = support.SARAPITests.completed
    import_csv = network_support.NetworkAPITests.import_csv
    start = network_support.NetworkAPITests.start

    def test_new_coverage_is_explicit_and_old_transport_is_not_relabelled(self):
        _, current = discover_sites([], {"id": "independent", "revision": 1})
        parsed = StudyDiscovery.model_validate(current)
        self.assertTrue(parsed.multiple_bond_boundaries)
        self.assertEqual(parsed.method, "single-region-three-port-multiple-h-v6")
        historical = {
            key: value
            for key, value in current.items()
            if key != "multiple_bond_boundaries"
        }
        historical["method"] = "single-region-three-port-aromatic-h-v5"
        self.assertEqual(
            StudyDiscovery.model_validate(historical).model_dump(), historical
        )
        for forged in (
            {**current, "multiple_bond_boundaries": False},
            {
                key: value
                for key, value in current.items()
                if key != "multiple_bond_boundaries"
            },
            {**historical, "multiple_bond_boundaries": True},
            {**current, "aromatic_boundaries": False},
        ):
            with self.assertRaises(ValueError):
                StudyDiscovery.model_validate(forged)

    def test_native_minimal_sites_activity_pk_structures_and_source_exports(self):
        with self.client() as client:
            dataset = self.import_csv(client, CSV)
            job = self.start(client, dataset)
            path = support.ROOT + "/jobs/" + job["id"] + "/study"
            report = client.get(path).json()["report"]
            self.assertTrue(report["discovery"]["multiple_bond_boundaries"])
            before = client.get(path + "/export?format=json").content
            rows = client.get(path + "/rows").json()["items"]
            ids = {row["label"]: row["molecule_id"] for row in rows}
            for left, right, delta in (("A1", "A2", -9), ("B1", "B2", -18)):
                for reference, candidate, sign in ((left, right, 1), (right, left, -1)):
                    with self.subTest(reference=reference, candidate=candidate):
                        sites = [
                            item
                            for item in report["regions"]
                            if item["reference_label"] == reference
                            and len(item["region"]["atom_indices"]) == 1
                            and item["region"]["attachment_count"] == 1
                            and any(
                                ids[candidate] in fragment["molecule_ids"]
                                for fragment in item["fragments"]
                            )
                        ]
                        self.assertEqual(len(sites), 1)
                        summary = sites[0]
                        region = summary["region"]["id"]
                        response = client.get(
                            path + "/preview",
                            params={"region_id": region, "molecule_id": ids[candidate]},
                        )
                        self.assertEqual(response.status_code, 200, response.text)
                        preview = response.json()
                        self.assertEqual(
                            len(preview["pair"]["variable_atom_indices"]), 1
                        )
                        self.assertEqual(len(preview["pair"]["attachment_mapping"]), 1)
                        units = {
                            item["unit"]: item["id"] for item in report["contexts"]
                        }
                        measured = {
                            item["context_id"]: item for item in preview["measurements"]
                        }
                        self.assertEqual(
                            measured[units["nM"]]["raw_difference"], sign * delta
                        )
                        self.assertEqual(
                            measured[units["h"]]["raw_difference"], sign * 2
                        )
                        self.assertGreater(
                            preview["candidate"]["properties"]["molecular_weight"], 0
                        )
                        for fragment in summary["fragments"]:
                            self.assertIn(
                                "=" if reference.startswith("A") else "#",
                                fragment["smiles"],
                            )
                            drawing = client.get(
                                path + "/drawing",
                                params={
                                    "kind": "fragment",
                                    "identifier": fragment["id"],
                                    "region_id": region,
                                },
                            )
                            self.assertEqual(drawing.status_code, 200, drawing.text)
                            self.assertIn("<svg", drawing.json()["svg"])
                        if reference == "A1":
                            self.assertEqual(
                                client.get(
                                    path + "/preview",
                                    params={
                                        "region_id": region,
                                        "molecule_id": ids["A3"],
                                    },
                                ).status_code,
                                422,
                            )
            self.assertEqual(client.get(path + "/export?format=json").content, before)
            self.assertEqual(client.get(path + "/export?format=html").status_code, 200)
            self.assertEqual(client.get(path + "/export?format=sdf").status_code, 200)
            self.assertGreater(
                next(row for row in rows if row["label"] == "A3")["properties"][
                    "molecular_weight"
                ],
                0,
            )
