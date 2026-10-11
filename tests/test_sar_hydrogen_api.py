"""Ordinary-H discovery, native publication, preview and persistent selection."""

import unittest

import test_sar_api as support
import test_sar_network_api as network_support
from test_web_support import WebFixture

CSV = b"id,smiles,IC50 (nM),t_half (h),target,assay,cells,duration\n1,COc1ccccc1Cl,10,1,T,controlled,C,1h\n2,COc1c(F)cccc1Cl,1,2,T,controlled,C,1h\n3,COc1c(C)cccc1Cl,,3,T,controlled,C,1h\n4,COc1ccc(F)cc1Cl,0.1,4,T,controlled,C,1h\n"


class HydrogenAPITests(WebFixture, unittest.TestCase):
    completed = support.SARAPITests.completed
    import_csv = network_support.NetworkAPITests.import_csv
    start = network_support.NetworkAPITests.start

    def test_hydrogen_native_discovery_bidirectional_preview_and_immutable_exports(
        self,
    ):
        with self.client() as client:
            dataset = self.import_csv(client, CSV)
            job = self.start(client, dataset)
            path = support.ROOT + "/jobs/" + job["id"] + "/study"
            reply = client.get(path)
            self.assertEqual(reply.status_code, 200, reply.text)
            report = reply.json()["report"]
            self.assertEqual(
                report["discovery"]["method"], "single-region-one-to-three-cut-h-v4"
            )
            self.assertGreater(report["discovery"]["indexed_hydrogen_sites"], 0)
            source = client.get(path + "/export?format=json").json()
            ids = {
                row["label"]: row["molecule_id"]
                for row in client.get(path + "/rows").json()["items"]
            }
            for left, right, is_hydrogen in (("1", "2", True), ("2", "1", False)):
                choices = [
                    item
                    for item in report["regions"]
                    if item["reference_label"] == left
                    and (item["region"]["hydrogen_anchor"] is not None) == is_hydrogen
                    and any(
                        ids[right] in fragment["molecule_ids"]
                        for fragment in item["fragments"]
                    )
                ]
                self.assertTrue(choices, (left, right))
                region = min(
                    choices, key=lambda item: len(item["region"]["atom_indices"])
                )["region"]
                response = client.get(
                    path + "/preview",
                    params={"region_id": region["id"], "molecule_id": ids[right]},
                )
                self.assertEqual(response.status_code, 200, response.text)
                preview = response.json()
                if is_hydrogen:
                    self.assertEqual(
                        (region["atom_indices"], region["hydrogen_anchor"]), ([], 3)
                    )
                    self.assertEqual(preview["pair"]["variable_atom_indices"], [4])
                else:
                    self.assertEqual(preview["pair"]["variable_atom_indices"], [])
                    self.assertEqual(preview["pair"]["candidate_hydrogen_anchor"], 3)
                values = {
                    context["unit"]: context["id"] for context in report["contexts"]
                }
                measured = {
                    item["context_id"]: item for item in preview["measurements"]
                }
                self.assertEqual(
                    measured[values["nM"]]["raw_difference"], -9 if is_hydrogen else 9
                )
                self.assertEqual(
                    measured[values["h"]]["raw_difference"], 1 if is_hydrogen else -1
                )
                image = client.get(
                    path + "/drawing",
                    params={
                        "kind": "molecule",
                        "identifier": ids[right],
                        "region_id": region["id"],
                    },
                )
                self.assertEqual(image.status_code, 200, image.text)
                self.assertIn("<svg", image.json()["svg"])
            self.assertEqual(
                client.get(path + "/export?format=json").json()["input"],
                source["input"],
            )
            self.assertEqual(
                client.get(path + "/export?format=json").json()["report"],
                source["report"],
            )
            self.assertEqual(client.get(path + "/export?format=html").status_code, 200)
            with client.app.state.workspace.store.connect() as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
                )

    def test_manual_hydrogen_region_is_bound_and_invalid_geometry_is_refused(self):
        with self.client() as client:
            dataset = self.import_csv(client, CSV)
            path = support.ROOT + "/datasets/" + dataset["id"]
            molecule = next(
                row
                for row in client.get(path + "/molecules").json()["items"]
                if row["label"] == "1"
            )
            request = {
                "molecule_id": molecule["id"],
                "expected_dataset_revision": 1,
                "expected_graph_sha256": molecule["graph_sha256"],
                "atom_indices": [],
                "hydrogen_anchor": 3,
                "name": "H1",
            }
            reply = client.post(path + "/regions", json=request)
            self.assertEqual(reply.status_code, 201, reply.text)
            region = reply.json()
            self.assertEqual(
                (
                    region["hydrogen_anchor"],
                    region["atom_indices"],
                    region["attachment_count"],
                ),
                (3, [], 1),
            )
            for change in (
                {"hydrogen_anchor": 1},
                {"hydrogen_anchor": True},
                {"hydrogen_anchor": 512},
                {"atom_indices": [3]},
                {"kind": "core"},
            ):
                response = client.post(path + "/regions", json={**request, **change})
                self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(
                client.post(path + "/regions", json=request).json()["id"], region["id"]
            )


if __name__ == "__main__":
    unittest.main()
