"""Native aromatic-point studies, explicit partial fragments and intact parents."""

import unittest

import test_sar_api as support
import test_sar_network_api as network_support
from test_web_support import WebFixture

CSV = b"id,smiles,IC50 (nM),t_half (h),target,assay,cells,duration\n1,COc1ccccc1Cl,10,1,T,controlled,C,1h\n2,COc1ccncc1Cl,1,3,T,controlled,C,1h\n3,COc1cnccc1Cl,,4,T,controlled,C,1h\n"


class AromaticAPITests(WebFixture, unittest.TestCase):
    completed = support.SARAPITests.completed
    import_csv = network_support.NetworkAPITests.import_csv
    start = network_support.NetworkAPITests.start

    def test_aromatic_auto_study_fragment_svg_activity_pk_and_exports(self):
        with self.client() as client:
            dataset = self.import_csv(client, CSV)
            job = self.start(client, dataset)
            path = support.ROOT + "/jobs/" + job["id"] + "/study"
            report = client.get(path).json()["report"]
            self.assertTrue(report["discovery"]["aromatic_boundaries"])
            rows = client.get(path + "/rows").json()["items"]
            ids = {row["label"]: row["molecule_id"] for row in rows}
            archived = client.get(path + "/export?format=json").json()
            for left, right, sign in (("1", "2", 1), ("2", "1", -1)):
                regions = [
                    item
                    for item in report["regions"]
                    if item["reference_label"] == left
                    and len(item["region"]["atom_indices"]) == 1
                    and any(
                        ids[right] in fragment["molecule_ids"]
                        for fragment in item["fragments"]
                    )
                ]
                self.assertTrue(regions)
                region = regions[0]
                for fragment in region["fragments"]:
                    self.assertEqual(fragment["representation"], "aromatic_graph")
                    self.assertIsNone(fragment["smiles"])
                    self.assertTrue(fragment["graph_smiles"])
                    image = client.get(
                        path + "/drawing",
                        params={
                            "kind": "fragment",
                            "identifier": fragment["id"],
                            "region_id": region["region"]["id"],
                        },
                    )
                    self.assertEqual(image.status_code, 200, image.text)
                    self.assertIn("<svg", image.json()["svg"])
                preview = client.get(
                    path + "/preview",
                    params={
                        "region_id": region["region"]["id"],
                        "molecule_id": ids[right],
                    },
                )
                self.assertEqual(preview.status_code, 200, preview.text)
                measurements = {
                    item["context_id"]: item for item in preview.json()["measurements"]
                }
                contexts = {item["unit"]: item["id"] for item in report["contexts"]}
                self.assertEqual(
                    measurements[contexts["nM"]]["raw_difference"], -9 * sign
                )
                self.assertEqual(
                    measurements[contexts["h"]]["raw_difference"], 2 * sign
                )
            for row in rows:
                self.assertTrue(row["eligible"])
                self.assertGreater(row["properties"]["molecular_weight"], 0)
            self.assertTrue(
                all(row["smiles"] for row in archived["input"]["molecules"])
            )
            self.assertEqual(client.get(path + "/export?format=json").json(), archived)
            self.assertEqual(client.get(path + "/export?format=html").status_code, 200)
