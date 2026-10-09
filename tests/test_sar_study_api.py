"""Native study integration on owned synthetic inputs, not article validation."""

from __future__ import annotations

import unittest

from test_sar_api import ROOT, SARAPITests, nonce
from test_web_support import WebFixture

CSV = (
    b"id,smiles,IC50 (nM),assay\n"
    b"Example 10,COc1ccc(Cl)cc1,10,binding\n"
    b"Example 2,CCOc1ccc(Cl)cc1,1,binding\n"
    b"Example 3,CCOc1ccc(Br)cc1,0.1,binding\n"
    b"Example 4,COc1ccc(Cl)cc1,,binding\n"
)


class SARStudyAPITests(WebFixture, unittest.TestCase):
    dataset = SARAPITests.dataset
    region = SARAPITests.region
    completed = SARAPITests.completed

    def start(self, client, dataset, region_ids=None, core_ids=None):
        prefix = ROOT + "/datasets/" + dataset["id"]
        profile = client.get(prefix + "/profile")
        self.assertEqual(profile.status_code, 200, profile.text)
        body = {
            "request_id": nonce(),
            "expected_dataset_revision": 1,
            "title": "Synthetic evidence study",
            "region_ids": region_ids or [],
            "core_ids": core_ids or [],
            "policies": [
                {
                    "context_id": profile.json()["contexts"][0]["id"],
                    "direction": "lower",
                    "strong_threshold": 2,
                }
            ],
            "confirm_context": True,
        }
        reply = client.post(prefix + "/studies", json=body)
        self.assertEqual(reply.status_code, 202, reply.text)
        return reply.json(), body

    def test_native_multi_region_report_views_exports_and_source_order(self):
        with self.client() as client:
            dataset = self.dataset(client, CSV)
            first = self.region(client, dataset)
            prefix = ROOT + "/datasets/" + dataset["id"]
            second = client.post(
                prefix + "/regions",
                json={
                    "molecule_id": first["molecule_id"],
                    "expected_dataset_revision": 1,
                    "expected_graph_sha256": first["graph_sha256"],
                    "atom_indices": first["atom_indices"],
                    "name": "Linker R2",
                },
            )
            self.assertEqual(second.status_code, 201, second.text)
            second = second.json()
            self.assertNotEqual(first["id"], second["id"])
            job, body = self.start(client, dataset, [first["id"], second["id"]])
            job = self.completed(client, job)
            self.assertEqual(job["kind"], "study")
            self.assertEqual(job["total"], 4 + 2 * 3)
            path = ROOT + "/jobs/" + job["id"] + "/study"
            result = client.get(path)
            self.assertEqual(result.status_code, 200, result.text)
            report = result.json()["report"]
            self.assertEqual(report["molecule_count"], 4)
            self.assertEqual(report["strict_pair_count"], 6)
            self.assertEqual(len(report["regions"]), 2)
            self.assertEqual(report["rows"], [])
            self.assertEqual(report["distributions"][0]["missing_molecules"], 1)
            all_rows = client.get(path + "/rows?page_size=2").json()
            self.assertEqual(all_rows["total"], 4)
            self.assertEqual(
                [item["label"] for item in all_rows["items"]],
                ["Example 2", "Example 3"],
            )
            strong = client.get(path + "/rows?scope=strong").json()
            self.assertEqual(
                {item["label"] for item in strong["items"]}, {"Example 2", "Example 3"}
            )
            missing = client.get(path + "/rows?query=Example+4").json()["items"][0]
            self.assertGreater(missing["properties"]["molecular_weight"], 0)
            self.assertEqual(missing["prediction_origin"], "not_provided")
            full = client.get(path + "/export?format=json").json()
            self.assertEqual(len(full["report"]["rows"]), 4)
            self.assertEqual(len(full["input"]["molecules"]), 4)
            self.assertFalse(full["report"]["article_algorithm_reproduced"])
            self.assertIn(b"Example 4", client.get(path + "/export?format=csv").content)
            self.assertEqual(
                client.get(path + "/export?format=sdf").content.count(b"$$$$"), 4
            )
            html = client.get(path + "/export?format=html")
            self.assertEqual(html.status_code, 200, html.text)
            if report["regions"][0]["no_variation"]:
                self.assertIn("No selected-region variation", html.text)
            self.assertIn("Synthetic evidence study", html.text)
            self.assertIn("stack vertical", html.text)
            self.assertIn("reference region map", html.text)
            self.assertIn("All source records", html.text)
            self.assertIn("source IDs / records", html.text)
            self.assertIn("data:image/svg+xml;base64,", html.text)
            self.assertNotIn("<script", html.text)
            drawing = client.get(
                path
                + "/drawing?kind=molecule&identifier="
                + first["molecule_id"]
                + "&region_id="
                + first["id"]
            )
            self.assertEqual(drawing.status_code, 200, drawing.text)
            self.assertIn("</svg>", drawing.json()["svg"])
            repeat = client.post(prefix + "/studies", json=body)
            self.assertEqual(repeat.json()["id"], job["id"])
            self.assertEqual(
                client.get(path + "/rows?fragment_id=foreign").status_code, 422
            )
            self.assertEqual(client.get(path + "/rows?scope=invalid").status_code, 422)
            self.assertEqual(
                client.get(path + "/drawing?kind=unknown&identifier=x").status_code, 422
            )
            with client.app.state.workspace.store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
                )

    def test_1191_records_are_not_truncated_to_1000(self):
        data = b"id,smiles,IC50 (nM),assay\n" + b"".join(
            f"I-{index},COc1ccc(Cl)cc1,{index % 17 + 1},binding\n".encode()
            for index in range(1, 1192)
        )
        with self.client() as client:
            dataset = self.dataset(client, data)
            job, _ = self.start(client, dataset)
            job = self.completed(client, job)
            path = ROOT + "/jobs/" + job["id"] + "/study"
            report = client.get(path).json()["report"]
            self.assertEqual(report["molecule_count"], 1191)
            self.assertEqual(report["distributions"][0]["observations"], 1191)
            page = client.get(path + "/rows?page=6&page_size=200").json()
            self.assertEqual(page["total"], 1191)
            self.assertEqual(len(page["items"]), 191)
            self.assertEqual(page["items"][-1]["label"], "I-1191")
            self.assertEqual(
                len(client.get(path + "/export?format=json").json()["report"]["rows"]),
                1191,
            )

    def test_full_core_is_descriptive_and_never_relaxes_a_variable_region(self):
        with self.client() as client:
            dataset = self.dataset(client, CSV)
            prefix = ROOT + "/datasets/" + dataset["id"]
            molecule = client.get(prefix + "/molecules").json()["items"][0]
            atoms = client.get(
                prefix + "/molecules/" + molecule["id"] + "/drawing"
            ).json()["atoms"]
            body = {
                "molecule_id": molecule["id"],
                "expected_dataset_revision": 1,
                "expected_graph_sha256": molecule["graph_sha256"],
                "atom_indices": [atom["index"] for atom in atoms],
                "name": "Full confirmed core",
            }
            self.assertEqual(
                client.post(prefix + "/regions", json=body).status_code, 422
            )
            body["kind"] = "core"
            core = client.post(prefix + "/regions", json=body)
            self.assertEqual(core.status_code, 201, core.text)
            self.assertEqual(core.json()["attachment_count"], 0)
            job, _ = self.start(client, dataset, core_ids=[core.json()["id"]])
            job = self.completed(client, job)
            report = client.get(ROOT + "/jobs/" + job["id"] + "/study").json()["report"]
            selected = [
                item
                for item in report["scaffolds"]
                if item["assignment_kind"] == "confirmed_core"
            ]
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["molecule_count"], 2)
            self.assertTrue(selected[0]["descriptive_only"])

    def test_exact_context_choices_and_grade_policy_validation(self):
        data = (
            b"id,smiles,IC50 (nM),assay,cell\nref,CO,1,binding,A\nv1,CCO,1,binding,B\n"
        )
        with self.client() as client:
            preview = client.post(
                ROOT + "/csv/preview?filename=context.csv", content=data
            ).json()
            dataset = client.post(
                ROOT + "/datasets/csv",
                json={
                    "token": preview["token"],
                    "title": "Contexts",
                    "id_column": "id",
                    "smiles_column": "smiles",
                    "activity_columns": ["IC50 (nM)"],
                    "assay_column": "assay",
                    "cell_line_column": "cell",
                    "request_id": nonce(),
                },
            ).json()
            prefix = ROOT + "/datasets/" + dataset["id"]
            profile = client.get(prefix + "/profile").json()
            self.assertEqual(len(profile["contexts"]), 2)
            self.assertEqual(
                {item["context"]["cell_line"] for item in profile["contexts"]},
                {"A", "B"},
            )
            body = {
                "request_id": nonce(),
                "expected_dataset_revision": 1,
                "title": "Invalid",
                "policies": [
                    {
                        "context_id": profile["contexts"][0]["id"],
                        "direction": "lower",
                        "grade_order": ["A", "A"],
                    }
                ],
            }
            self.assertEqual(
                client.post(prefix + "/studies", json=body).status_code, 422
            )
            body["policies"][0]["grade_order"] = ["A", "B"]
            body["policies"][0]["strong_threshold"] = 1
            self.assertEqual(
                client.post(prefix + "/studies", json=body).status_code, 422
            )
            body["policies"][0]["strong_threshold"] = None
            body["policies"][0]["context_id"] = "0" * 64
            self.assertEqual(
                client.post(prefix + "/studies", json=body).status_code, 422
            )
