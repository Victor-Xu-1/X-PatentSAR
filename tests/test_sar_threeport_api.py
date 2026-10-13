"""Native three-port studies preserve measurements, source and one queue."""

import unittest

import test_sar_api as support
import test_sar_network_api as network_support
from test_web_support import WebFixture

from patent_sar_extractor.core.sar.discovery import discover_sites
from patent_sar_extractor.web.sar.study_models import StudyDiscovery

CSV = b"id,smiles,IC50 (nM),t_half (h),target,assay,cells,duration\n1,COC(c1ccccc1)Nc1ncccc1,10,1,T,controlled,C,1h\n2,CON(c1ccccc1)Nc1ncccc1,1,3,T,controlled,C,1h\n3,COC(C)(c1ccccc1)Nc1ncccc1,,4,T,controlled,C,1h\n4,FC1CC2CCC1C2N,20,4,T,controlled,C,1h\n5,FC1CN2CCC1C2N,2,6,T,controlled,C,1h\n-,CO,0.00001,99,T,controlled,C,1h\nIntermediate 18,CCO,0.00001,99,T,controlled,C,1h\n"


class ThreeportAPITests(WebFixture, unittest.TestCase):
    completed = support.SARAPITests.completed
    import_csv = network_support.NetworkAPITests.import_csv
    start = network_support.NetworkAPITests.start

    def test_typed_discovery_preserves_legacy_and_refuses_wrong_port_claims(self):
        _, current = discover_sites([], {"id": "empty", "revision": 1})
        self.assertEqual(
            StudyDiscovery.model_validate(current).method, current["method"]
        )
        for method, ports in (
            ("single-non-ring-bond-v1", 1),
            ("single-region-one-two-cut-v2", 2),
            ("single-region-one-two-cut-h-v3", 2),
        ):
            payload = {
                **current,
                "method": method,
                "max_cut_bonds": ports,
                "aromatic_boundaries": False,
                "multiple_bond_boundaries": False,
            }
            self.assertEqual(
                StudyDiscovery.model_validate(payload).max_cut_bonds, ports
            )
            with self.assertRaises(ValueError):
                StudyDiscovery.model_validate({**payload, "max_cut_bonds": 3})
        for payload in (
            {**current, "max_cut_bonds": 2},
            {**current, "indexed_hydrogen_sites": current["indexed_cuts"] + 1},
            {
                key: value
                for key, value in current.items()
                if key != "indexed_hydrogen_sites"
            },
            {
                key: value
                for key, value in current.items()
                if key != "examined_boundaries"
            },
        ):
            with self.assertRaises(ValueError):
                StudyDiscovery.model_validate(payload)

    def test_native_three_port_structures_activity_pk_and_exports(self):
        with self.client() as client:
            dataset = self.import_csv(client, CSV)
            self.assertEqual((dataset["input_row_count"], dataset["row_count"]), (7, 5))
            job = self.start(client, dataset)
            path = support.ROOT + "/jobs/" + job["id"] + "/study"
            report = client.get(path).json()["report"]
            self.assertEqual(
                report["discovery"]["method"], "single-region-three-port-multiple-h-v6"
            )
            self.assertEqual(report["discovery"]["max_cut_bonds"], 3)
            originals = client.get(path + "/export?format=json").json()
            items = client.get(path + "/rows").json()["items"]
            ids = {row["label"]: row["molecule_id"] for row in items}
            for left, right, activity_delta in (("1", "2", -9), ("4", "5", -18)):
                for reference_label, candidate_label, direction in (
                    (left, right, 1),
                    (right, left, -1),
                ):
                    summaries = [
                        summary
                        for summary in report["regions"]
                        if summary["reference_label"] == reference_label
                        and summary["region"]["attachment_count"] == 3
                        and any(
                            ids[candidate_label] in fragment["molecule_ids"]
                            for fragment in summary["fragments"]
                        )
                    ]
                    self.assertTrue(summaries, (reference_label, candidate_label))
                    summary = min(
                        summaries, key=lambda item: len(item["region"]["atom_indices"])
                    )
                    response = client.get(
                        path + "/preview",
                        params={
                            "region_id": summary["region"]["id"],
                            "molecule_id": ids[candidate_label],
                        },
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    preview = response.json()
                    self.assertEqual(len(preview["pair"]["attachment_mapping"]), 3)
                    measurements = {
                        row["context_id"]: row for row in preview["measurements"]
                    }
                    contexts = {
                        context["unit"]: context["id"] for context in report["contexts"]
                    }
                    self.assertEqual(
                        measurements[contexts["nM"]]["raw_difference"],
                        direction * activity_delta,
                    )
                    self.assertEqual(
                        measurements[contexts["h"]]["raw_difference"], direction * 2
                    )
                    for drawing in (preview["reference"], preview["candidate"]):
                        self.assertGreater(drawing["properties"]["molecular_weight"], 0)
                        self.assertIsNone(drawing["properties"]["Solubility_AqSolDB"])
            missing = next(row for row in items if row["label"] == "3")
            self.assertGreater(missing["properties"]["molecular_weight"], 0)
            self.assertTrue(missing["eligible"])
            self.assertEqual(client.get(path + "/export?format=json").json(), originals)
            self.assertEqual(client.get(path + "/export?format=html").status_code, 200)
            with client.app.state.workspace.store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
                )
