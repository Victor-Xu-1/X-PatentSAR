"""Native, immutable preview contract; no chemical modification or model call."""

import json
import unittest

import test_sar_api as support
from test_web_support import WebFixture
from patent_sar_extractor.core.sar.values import parse_value
from patent_sar_extractor.web.sar.study_preview import _scalar_difference


class SARPreviewTests(WebFixture, unittest.TestCase):
    completed = support.SARAPITests.completed
    region = support.SARAPITests.region

    def test_display_difference_is_exact_or_explicitly_unrepresentable(self):
        def delta(a, b):
            return _scalar_difference(parse_value(a, {}), parse_value(b, {}))

        self.assertEqual(delta("1", "1." + "0" * 100 + "1"), 1e-101)
        self.assertEqual(delta("10", "1"), -9)
        self.assertEqual(delta("1e308", "1e308"), 0)
        self.assertIsNone(delta("1e-308", "1.0000000000000001e-308"))
        self.assertIsNone(delta("-1e308", "1e308"))
        self.assertIsNone(delta("<10", "1"))

    def test_exact_values_deltas_graph_proof_and_immutable_input(self):
        with self.client() as client:
            data = b"id,smiles,IC50 (nM),target,assay,cells,duration\nP1,COc1ccc(Cl)cc1,10,T,binding,C,2h\nP2,CCOc1ccc(Cl)cc1,1,T,binding,C,2h\nP3,CCOc1ccc(Br)cc1,0.1,T,binding,C,2h\n"
            token = client.post(
                support.ROOT + "/csv/preview?filename=preview.csv", content=data
            ).json()["token"]
            response = client.post(
                support.ROOT + "/datasets/csv",
                json={
                    "token": token,
                    "title": "Preview controlled",
                    "id_column": "id",
                    "smiles_column": "smiles",
                    "activity_columns": ["IC50 (nM)"],
                    "target_column": "target",
                    "assay_column": "assay",
                    "cell_line_column": "cells",
                    "duration_column": "duration",
                    "request_id": support.nonce(),
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            dataset = response.json()
            region = self.region(client, dataset)
            prefix = support.ROOT + "/datasets/" + dataset["id"]
            context = client.get(prefix + "/profile").json()["contexts"][0]
            response = client.post(
                prefix + "/studies",
                json={
                    "request_id": support.nonce(),
                    "expected_dataset_revision": 1,
                    "title": "Preview",
                    "region_ids": [region["id"]],
                    "policies": [{"context_id": context["id"], "direction": "lower"}],
                },
            )
            self.assertEqual(response.status_code, 202, response.text)
            job = self.completed(client, response.json())
            path = support.ROOT + "/jobs/" + job["id"] + "/study"
            original = client.get(path + "/export?format=json").content
            rows = client.get(prefix + "/molecules").json()["items"]
            candidate = next(row for row in rows if row["label"] == "P2")
            params = {"region_id": region["id"], "molecule_id": candidate["id"]}
            response = client.get(path + "/preview", params=params)
            self.assertEqual(response.status_code, 200, response.text)
            preview = response.json()
            measured = preview["measurements"][0]
            self.assertEqual(measured["reference_values"], ["10"])
            self.assertEqual(measured["candidate_values"], ["1"])
            self.assertEqual(measured["raw_difference"], -9)
            self.assertEqual(measured["comparison"], "better")
            self.assertAlmostEqual(
                preview["property_differences"]["molecular_weight"], 14.027, places=2
            )
            self.assertEqual(client.get(path + "/export?format=json").content, original)
            wrong = next(row for row in rows if row["label"] == "P3")
            self.assertEqual(
                client.get(
                    path + "/preview", params={**params, "molecule_id": wrong["id"]}
                ).status_code,
                422,
            )
            with client.app.state.sar.store.connect(write=True) as connection:
                saved = connection.execute(
                    "SELECT ordinal,payload FROM pairs WHERE job_id=? AND json_extract(payload,'$.molecule_id')=?",
                    (job["id"], candidate["id"]),
                ).fetchone()
                tampered = json.loads(saved["payload"])
                tampered["variable_atom_indices"] = [999]
                connection.execute(
                    "UPDATE pairs SET payload=? WHERE job_id=? AND ordinal=?",
                    (json.dumps(tampered), job["id"], saved["ordinal"]),
                )
            self.assertEqual(
                client.get(path + "/preview", params=params).status_code, 409
            )


if __name__ == "__main__":
    unittest.main()
