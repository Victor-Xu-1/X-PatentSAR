"""Real local SAR persistence/worker/API checks on isolated controlled inputs."""

from __future__ import annotations

import hashlib
import time
import unittest
import uuid

from fastapi.testclient import TestClient
from test_web_support import BASE_URL, WebFixture, artifact_run

CSV = b"id,smiles,IC50 (nM),assay\nExample 1,COc1ccc(Cl)cc1,10,binding\nI-255,CCOc1ccc(Cl)cc1,1,binding\n8B,CCOc1ccc(Br)cc1,0.1,binding\n"
ROOT = "/api/v1/sar"


def nonce():
    return uuid.uuid4().hex


class SARAPITests(WebFixture, unittest.TestCase):
    def dataset(self, client, data=CSV):
        response = client.post(
            ROOT + "/csv/preview?filename=controlled.csv",
            content=data,
            headers={"Content-Type": "text/csv"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        token = response.json()["token"]
        body = {
            "token": token,
            "title": "Controlled SAR",
            "id_column": "id",
            "smiles_column": "smiles",
            "activity_columns": ["IC50 (nM)"],
            "assay_column": "assay",
            "request_id": nonce(),
        }
        response = client.post(ROOT + "/datasets/csv", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        repeated = client.post(ROOT + "/datasets/csv", json=body)
        self.assertEqual(repeated.json()["id"], response.json()["id"])
        return response.json()

    def region(self, client, dataset):
        prefix = ROOT + "/datasets/" + dataset["id"]
        rows = client.get(prefix + "/molecules").json()["items"]
        reference = rows[0]
        draw = client.get(prefix + "/molecules/" + reference["id"] + "/drawing")
        self.assertEqual(draw.status_code, 200, draw.text)
        self.assertIn("</svg>", draw.json()["svg"])
        response = client.post(
            prefix + "/regions",
            json={
                "molecule_id": reference["id"],
                "expected_dataset_revision": dataset["revision"],
                "expected_graph_sha256": reference["graph_sha256"],
                "atom_indices": [0],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def completed(self, client, job):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = client.get(ROOT + "/jobs/" + job["id"])
            self.assertEqual(response.status_code, 200, response.text)
            value = response.json()
            if value["status"] not in {"queued", "running"}:
                self.assertEqual(value["status"], "complete", value)
                return value
            time.sleep(0.03)
        self.fail("Bounded controlled SAR worker did not complete")

    def test_identical_region_retry_returns_original_receipt_without_duplicate_or_job(
        self,
    ):
        with self.client() as client:
            dataset = self.dataset(client)
            prefix = ROOT + "/datasets/" + dataset["id"]
            reference = client.get(prefix + "/molecules").json()["items"][0]
            body = {
                "molecule_id": reference["id"],
                "expected_dataset_revision": dataset["revision"],
                "expected_graph_sha256": reference["graph_sha256"],
                "atom_indices": [0, 1],
                "name": "Original R test",
                "kind": "variable",
            }
            first = client.post(prefix + "/regions", json=body)
            self.assertEqual(first.status_code, 201, first.text)
            repeated = client.post(prefix + "/regions", json=body)
            reordered = client.post(
                prefix + "/regions", json={**body, "atom_indices": [1, 0]}
            )
            self.assertEqual(repeated.status_code, 201, repeated.text)
            self.assertEqual(reordered.status_code, 201, reordered.text)
            self.assertEqual(first.json(), repeated.json())
            self.assertEqual(first.json(), reordered.json())
            self.assertEqual(
                client.get(prefix + "/profile").json()["regions"], [first.json()]
            )
            self.assertEqual(client.get(prefix + "/jobs").json()["items"], [])
            with client.app.state.workspace.store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
                )

    def test_real_worker_csv_region_activity_and_exports_without_extraction_job(self):
        with self.client() as client:
            dataset = self.dataset(client)
            self.assertEqual(dataset["input_row_count"], 3)
            self.assertEqual(dataset["eligible_count"], 3)
            region = self.region(client, dataset)
            request = {
                "request_id": nonce(),
                "expected_dataset_revision": 1,
                "region_id": region["id"],
                "metric_id": dataset["metrics"][0]["id"],
                "direction": "lower",
                "confirm_context": True,
            }
            response = client.post(
                ROOT + "/datasets/" + dataset["id"] + "/jobs", json=request
            )
            self.assertEqual(response.status_code, 202, response.text)
            job = self.completed(client, response.json())
            path = ROOT + "/jobs/" + job["id"]
            pairs = client.get(path + "/pairs").json()["items"]
            self.assertEqual(len(pairs), 2)
            self.assertEqual(pairs[0]["match_status"], "matched")
            self.assertEqual(pairs[0]["comparison"], "better")
            self.assertAlmostEqual(pairs[0]["fold_change"], 10)
            self.assertEqual(pairs[1]["match_status"], "not_matched")
            self.assertEqual(pairs[1]["comparison"], "indeterminate")
            exported = client.get(path + "/export?format=json")
            self.assertEqual(exported.status_code, 200, exported.text)
            report = exported.json()
            self.assertTrue(report["research_only"])
            self.assertFalse(report["article_reproduction"])
            self.assertEqual(len(report["molecules"]), 3)
            self.assertEqual(report["region"]["atom_indices"], [0])
            self.assertEqual(report["job"]["input_sha256"], job["input_sha256"])
            self.assertIn(b"I-255", client.get(path + "/export?format=csv").content)
            self.assertEqual(
                client.post(
                    ROOT + "/datasets/" + dataset["id"] + "/jobs", json=request
                ).json()["id"],
                job["id"],
            )
            with client.app.state.workspace.store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
                )

    def test_project_snapshot_reads_effective_correction_without_rewriting_artifacts(
        self,
    ):
        run = artifact_run(self.root / "source", self.pdf, current=True, rows=2)
        before = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in run.rglob("*")
            if path.is_file()
        }
        with self.client(import_runs=[run]) as client:
            project = client.get("/api/v1/projects").json()["items"][0]
            response = client.post(
                ROOT + "/datasets/project",
                json={"project_id": project["id"], "request_id": nonce()},
            )
            self.assertEqual(response.status_code, 201, response.text)
            dataset = response.json()
            self.assertEqual(dataset["row_count"], 2)
            self.assertEqual(dataset.get("source_acceptance"), project["acceptance"])
            self.assertEqual(
                dataset.get("source_page_count"), project["pdf"]["page_count"]
            )
            rows = client.get(
                ROOT + "/datasets/" + dataset["id"] + "/molecules"
            ).json()["items"]
            self.assertTrue(all(row["source_compound_id"] for row in rows))
            correction = client.get(
                f"/api/v1/projects/{project['id']}/structures/Compound%201/correction"
            ).json()
            fields = correction["values"]
            fields["display_id"] = "Original Example A"
            changed = client.put(
                f"/api/v1/projects/{project['id']}/structures/Compound%201/correction",
                json={
                    "expected_revision": correction["revision"],
                    "expected_source_fingerprint": correction["source_fingerprint"],
                    "fields": fields,
                },
            )
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertTrue(
                client.get(ROOT + "/datasets/" + dataset["id"]).json()["stale"]
            )
            refreshed = client.post(
                ROOT + "/datasets/project",
                json={"project_id": project["id"], "request_id": nonce()},
            )
            self.assertEqual(refreshed.status_code, 201, refreshed.text)
            labels = client.get(
                ROOT + "/datasets/" + refreshed.json()["id"] + "/molecules"
            ).json()["items"]
            self.assertEqual(labels[0]["label"], "Original Example A")
        self.assertEqual(
            before,
            {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in run.rglob("*")
                if path.is_file()
            },
        )

    def test_csv_and_regions_require_existing_auth_csrf_and_exact_graph_revision(self):
        with TestClient(self.app(), base_url=BASE_URL) as client:
            self.assertEqual(client.get(ROOT + "/datasets").status_code, 401)
            client.get("/api/v1/session")
            self.assertEqual(
                client.post(
                    ROOT + "/csv/preview?filename=x.csv", content=CSV
                ).status_code,
                403,
            )
        with self.client() as client:
            dataset = self.dataset(client)
            row = client.get(ROOT + "/datasets/" + dataset["id"] + "/molecules").json()[
                "items"
            ][0]
            for fields in (
                {"expected_graph_sha256": "0" * 64},
                {"expected_dataset_revision": 2},
                {"atom_indices": [999]},
                {"atom_indices": [0, 0]},
            ):
                request = {
                    "molecule_id": row["id"],
                    "expected_graph_sha256": row["graph_sha256"],
                    "expected_dataset_revision": 1,
                    "atom_indices": [0],
                    **fields,
                }
                response = client.post(
                    ROOT + "/datasets/" + dataset["id"] + "/regions", json=request
                )
                self.assertIn(response.status_code, (409, 422), response.text)

    def test_removed_datasets_hidden_and_foreign_region_never_rebound(self):
        with self.client() as client:
            first, second = self.dataset(client), self.dataset(client)
            region = self.region(client, first)
            bad = client.post(
                ROOT + "/datasets/" + second["id"] + "/jobs",
                json={
                    "request_id": nonce(),
                    "expected_dataset_revision": 1,
                    "region_id": region["id"],
                    "metric_id": second["metrics"][0]["id"],
                    "direction": "lower",
                },
            )
            self.assertEqual(bad.status_code, 404)
            self.assertEqual(
                client.delete(ROOT + "/datasets/" + first["id"]).status_code, 204
            )
            self.assertEqual(
                client.get(ROOT + "/datasets/" + first["id"]).status_code, 404
            )
            with client.app.state.sar.store.connect() as connection:
                self.assertGreater(
                    connection.execute(
                        "SELECT COUNT(*) FROM molecules WHERE dataset_id=?",
                        (first["id"],),
                    ).fetchone()[0],
                    0,
                )


if __name__ == "__main__":
    unittest.main()
