"""Native, synthetic study: one complete potency policy across every consumer."""

import unittest

import test_sar_api as support
from test_web_support import WebFixture

ROOT = support.ROOT


class SARPotencyTests(WebFixture, unittest.TestCase):
    dataset = support.SARAPITests.dataset
    completed = support.SARAPITests.completed

    def run_study(self, client, values):
        csv = "id,smiles,IC50 (nM),target,assay,cell_line,duration\n" + "\n".join(
            f"S{index + 1},{'C' * (index + 1)}O,{raw},T,binding,C,2h"
            for index, raw in enumerate(values)
        )
        token = client.post(
            ROOT + "/csv/preview?filename=potency.csv", content=csv.encode()
        ).json()["token"]
        reply = client.post(
            ROOT + "/datasets/csv",
            json={
                "token": token,
                "title": "Controlled tenth-dose study",
                "id_column": "id",
                "smiles_column": "smiles",
                "activity_columns": ["IC50 (nM)"],
                "target_column": "target",
                "assay_column": "assay",
                "cell_line_column": "cell_line",
                "duration_column": "duration",
                "request_id": support.nonce(),
            },
        )
        self.assertEqual(reply.status_code, 201, reply.text)
        prefix = ROOT + "/datasets/" + reply.json()["id"]
        context = client.get(prefix + "/profile").json()["contexts"][0]
        body = {
            "request_id": support.nonce(),
            "expected_dataset_revision": 1,
            "title": "Native potency",
            "policies": [
                {
                    "context_id": context["id"],
                    "direction": "lower",
                    "strength_method": "tenth_decade",
                }
            ],
        }
        obsolete = {
            **body,
            "request_id": support.nonce(),
            "policies": [{**body["policies"][0], "strong_threshold": 2}],
        }
        self.assertEqual(
            client.post(prefix + "/studies", json=obsolete).status_code, 422
        )
        started = client.post(prefix + "/studies", json=body)
        self.assertEqual(started.status_code, 202, started.text)
        job = self.completed(client, started.json())
        return ROOT + "/jobs/" + job["id"] + "/study", context["id"]

    def test_whole_context_counts_rows_filters_exports_and_missing_structure_data(self):
        with self.client() as client:
            path, context = self.run_study(client, ["0.1"] * 9 + ["1", "10", "100", ""])
            before = client.get(path + "/export?format=json").content
            report = client.get(path).json()["report"]
            scale = report["policies"][0]["strength_scale"]
            self.assertEqual(
                (
                    scale["anchor_rank"],
                    scale["population"],
                    scale["strong_boundary"],
                    scale["medium_boundary"],
                ),
                (10, 12, 10, 100),
            )
            bins = {
                item["label"]: item["molecules"]
                for item in report["distributions"][0]["bins"]
            }
            self.assertEqual(
                (bins["strong"], bins["medium"], bins["weak"], bins["missing"]),
                (10, 1, 1, 1),
            )
            self.assertEqual(
                client.get(path + "/rows?scope=strong&page_size=2").json()["total"], 10
            )
            all_rows = client.get(path + "/rows?page_size=50").json()["items"]
            by_label = {row["label"]: row for row in all_rows}
            for label, tier in (
                ("S10", "strong"),
                ("S11", "medium"),
                ("S12", "weak"),
                ("S13", "unclassified"),
            ):
                self.assertEqual(by_label[label]["activity_bands"][context], tier)
            self.assertGreater(by_label["S13"]["properties"]["molecular_weight"], 0)
            self.assertEqual(by_label["S13"]["prediction_origin"], "not_provided")
            client.get(path + "/rows?query=S12&page_size=1")
            self.assertEqual(
                client.get(path).json()["report"]["policies"][0]["strength_scale"],
                scale,
            )
            self.assertEqual(client.get(path + "/export?format=json").content, before)
            self.assertIn(
                b"strength_policies", client.get(path + "/export?format=csv").content
            )
            self.assertIn(
                "Tenth potency decade", client.get(path + "/export?format=html").text
            )

    def test_censored_tenth_measurement_is_not_dropped_to_create_a_precise_anchor(self):
        with self.client() as client:
            path, context = self.run_study(client, ["1"] * 9 + ["<100"])
            report = client.get(path).json()["report"]
            self.assertEqual(
                report["policies"][0]["strength_scale"]["status"], "ambiguous"
            )
            self.assertIsNone(
                report["policies"][0]["strength_scale"]["strong_boundary"]
            )
            rows = client.get(path + "/rows").json()["items"]
            self.assertTrue(
                all(row["activity_bands"][context] == "unclassified" for row in rows)
            )
            self.assertIn(
                "<100", [value for row in rows for value in row["values"][context]]
            )


if __name__ == "__main__":
    unittest.main()
