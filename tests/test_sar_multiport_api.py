"""Native two-port linker/ring studies and actual value/property/PK previews."""

import unittest

import test_sar_api as support
import test_sar_network_api as network_support
from test_web_support import WebFixture

CSV = b"id,smiles,IC50 (nM),t_half (h),target,assay,cells,duration\n1,n1ccccc1COc1ccccc1F,10,1,T,controlled,C,1h\n2,n1ccccc1CCOc1ccccc1F,1,2,T,controlled,C,1h\n3,n1ccccc1C(C)COc1ccccc1F,,3,T,controlled,C,1h\n4,NC1COCC1F,20,4,T,controlled,C,1h\n5,NC1CCOCC1F,2,5,T,controlled,C,1h\n-,CO,0.00001,99,T,controlled,C,1h\nIntermediate 18,CCO,0.00001,99,T,controlled,C,1h\n"


class MultiportAPITests(WebFixture, unittest.TestCase):
    completed = support.SARAPITests.completed
    import_csv = network_support.NetworkAPITests.import_csv
    start = network_support.NetworkAPITests.start

    def test_two_port_linker_ring_and_pk_preview_through_the_one_native_queue(self):
        with self.client() as client:
            dataset = self.import_csv(client, CSV)
            self.assertEqual((dataset["input_row_count"], dataset["row_count"]), (7, 5))
            job = self.start(client, dataset)
            path = support.ROOT + "/jobs/" + job["id"] + "/study"
            report = client.get(path).json()["report"]
            self.assertEqual(
                report["discovery"]["method"], "single-region-one-to-three-cut-h-v4"
            )
            self.assertEqual(report["discovery"]["max_cut_bonds"], 3)
            ids = {
                row["label"]: row["molecule_id"]
                for row in client.get(path + "/rows").json()["items"]
            }
            for left, right, activity_delta in (("1", "2", -9), ("4", "5", -18)):
                summaries = [
                    summary
                    for summary in report["regions"]
                    if summary["reference_label"] == left
                    and summary["region"]["attachment_count"] == 2
                    and any(
                        ids[right] in fragment["molecule_ids"]
                        for fragment in summary["fragments"]
                    )
                ]
                self.assertTrue(summaries, (left, right))
                summary = min(
                    summaries, key=lambda item: len(item["region"]["atom_indices"])
                )
                reply = client.get(
                    path + "/preview",
                    params={
                        "region_id": summary["region"]["id"],
                        "molecule_id": ids[right],
                    },
                )
                self.assertEqual(reply.status_code, 200, reply.text)
                preview = reply.json()
                measured = {row["context_id"]: row for row in preview["measurements"]}
                by_unit = {
                    context["unit"]: context["id"] for context in report["contexts"]
                }
                self.assertEqual(
                    measured[by_unit["nM"]]["raw_difference"], activity_delta
                )
                self.assertEqual(measured[by_unit["h"]]["raw_difference"], 1)
                self.assertEqual(len(preview["pair"]["variable_atom_indices"]), 2)
                self.assertGreater(
                    preview["candidate"]["properties"]["molecular_weight"],
                    preview["reference"]["properties"]["molecular_weight"],
                )
                self.assertIsNone(
                    preview["candidate"]["properties"]["Solubility_AqSolDB"]
                )
                scope = client.get(
                    path + "/rows",
                    params={
                        "region_id": summary["region"]["id"],
                        "scope": "changes",
                        "page_size": 1,
                    },
                ).json()
                self.assertGreaterEqual(scope["total"], 1)
                self.assertNotIn(left, [row["label"] for row in scope["items"]])
            missing = client.get(path + "/rows?query=3").json()["items"][0]
            self.assertGreater(missing["properties"]["molecular_weight"], 0)
            exported = client.get(path + "/export?format=json").json()
            self.assertEqual(len(exported["input"]["molecules"]), 5)
            self.assertEqual(exported["report"]["discovery"]["max_cut_bonds"], 3)
            self.assertEqual(
                client.get(path + "/export?format=json").json()["input"],
                exported["input"],
            )
            with client.app.state.workspace.store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
                )
