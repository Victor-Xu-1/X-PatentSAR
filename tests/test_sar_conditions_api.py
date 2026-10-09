"""Native API declarations keep original evidence and source QA independent."""

import unittest

import test_sar_api as support
from test_web_support import WebFixture, artifact_run


class SARConditionsAPITests(WebFixture, unittest.TestCase):
    completed = support.SARAPITests.completed

    def prepare(self, client):
        project = client.get("/api/v1/projects").json()["items"][0]
        response = client.post(
            support.ROOT + "/datasets/project",
            json={"project_id": project["id"], "request_id": support.nonce()},
        )
        self.assertEqual(response.status_code, 201, response.text)
        dataset = response.json()
        prefix = support.ROOT + "/datasets/" + dataset["id"]
        profile = client.get(prefix + "/profile").json()
        context = profile["contexts"][0]
        missing = {
            key: value
            for key, value in {
                "target": "Target T",
                "assay": "Original assay method",
                "cell_line": "Cells C",
                "duration": "2 h",
            }.items()
            if context["context"].get(key) is None
        }
        declaration = {
            "context_id": context["id"],
            "fields": missing,
            "source_document_sha256": dataset["source_document_sha256"],
            "source_pages": [1],
            "note": "Source-anchored controlled declaration. Not automatic evidence verification.",
        }
        request = {
            "request_id": support.nonce(),
            "expected_dataset_revision": dataset["revision"],
            "title": "Declared context study",
            "policies": [{"context_id": context["id"], "direction": "lower"}],
            "context_declarations": [declaration],
        }
        return dataset, prefix, request

    def test_native_declared_context_and_export_preserve_original_observations_and_qa(
        self,
    ):
        run = artifact_run(self.root / "source", self.pdf, current=True, rows=2)
        with self.client(import_runs=[run]) as client:
            dataset, prefix, request = self.prepare(client)
            before = client.get(prefix + "/molecules").json()
            response = client.post(prefix + "/studies", json=request)
            self.assertEqual(response.status_code, 202, response.text)
            job = self.completed(client, response.json())
            exported = client.get(
                support.ROOT + "/jobs/" + job["id"] + "/study/export?format=json"
            ).json()
            self.assertEqual(
                exported["report"]["context_declarations"],
                request["context_declarations"],
            )
            self.assertEqual(
                exported["report"]["source_acceptance"], dataset["source_acceptance"]
            )
            self.assertEqual(
                exported["report"]["counting_contract"], "unique-molecules-v2"
            )
            self.assertEqual(
                [row["observations"] for row in exported["input"]["molecules"]],
                [row["observations"] for row in before["items"]],
            )
            self.assertEqual(client.get(prefix + "/molecules").json(), before)
            self.assertTrue(
                all(
                    "operator_declared_context_not_automatic_verification"
                    in row["reasons"]
                    for row in exported["report"]["rows"]
                )
            )
            csv = client.get(
                support.ROOT + "/jobs/" + job["id"] + "/study/export?format=csv"
            ).text
            self.assertIn("source_acceptance_state", csv)
            self.assertIn("counting_contract", csv)
            self.assertIn("context_declarations", csv)
            html = client.get(
                support.ROOT + "/jobs/" + job["id"] + "/study/export?format=html"
            ).text
            self.assertIn("Source-documented conditions", html)
            self.assertIn(request["context_declarations"][0]["note"], html)
            self.assertIn(dataset["source_document_sha256"], html)
            self.assertIn("Source extraction QA:", html)

    def test_foreign_source_declaration_is_rejected_before_a_job_is_created(self):
        run = artifact_run(self.root / "source", self.pdf, current=True, rows=2)
        with self.client(import_runs=[run]) as client:
            _, prefix, request = self.prepare(client)
            request["context_declarations"][0]["source_document_sha256"] = "0" * 64
            response = client.post(prefix + "/studies", json=request)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(response.json()["error"]["code"], "sar_conditions_invalid")
            self.assertEqual(client.get(prefix + "/jobs").json()["total"], 0)


if __name__ == "__main__":
    unittest.main()
