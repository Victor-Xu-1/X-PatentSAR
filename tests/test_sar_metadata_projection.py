"""Count evidence crosses real snapshot/persistence without becoming SAR data."""

import hashlib
import json
import unittest
import uuid
from dataclasses import asdict

from tests.test_activity_header_grid import observed_grid
from tests.test_web_support import WebFixture, artifact_run


class SARMetadataProjectionTests(WebFixture, unittest.TestCase):
    def test_project_snapshot_retains_count_source_but_only_imports_measurements(self):
        run = artifact_run(
            self.root / "source", self.pdf, current=True, accepted=False, rows=2
        )
        _, rows = observed_grid(
            [["No.", "IC50 (nM)", "n"], ["1", "12.4", "3"], ["2", "9.1", "2"]]
        )
        path = run / "activity/activity_data.json"
        payload = json.loads(path.read_text())
        payload["rows"] = [asdict(row) for row in rows]
        path.write_text(json.dumps(payload))
        before = {
            str(file): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in run.rglob("*")
            if file.is_file()
        }
        with self.client(import_runs=[run]) as client:
            project = client.get("/api/v1/projects").json()["items"][0]
            original = client.post(
                "/api/v1/projects/" + project["id"] + "/pdf?filename=source.pdf",
                content=self.pdf.read_bytes(),
                headers={"Content-Type": "application/pdf"},
            )
            self.assertEqual(original.status_code, 200, original.text)
            response = client.post(
                "/api/v1/sar/datasets/project",
                json={
                    "project_id": project["id"],
                    "request_id": uuid.uuid4().hex,
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            dataset = response.json()
            self.assertEqual(dataset["source_acceptance"]["state"], "failed")
            self.assertEqual(
                [metric["name"] for metric in dataset["metrics"]], ["IC50 (nM)"]
            )
            prefix = "/api/v1/sar/datasets/" + dataset["id"]
            imported = client.get(prefix + "/molecules").json()["items"]
            self.assertEqual(len(imported), 2)
            self.assertEqual([len(row["observations"]) for row in imported], [1, 1])
            self.assertEqual(
                {row["observations"][0]["value"] for row in imported}, {"12.4", "9.1"}
            )
            self.assertEqual(client.get(prefix + "/jobs").json()["items"], [])
            from patent_sar_extractor.web.sar.observation_contexts import (
                ObservationContexts,
            )

            contexts = ObservationContexts(
                client.app.state.workspace.store.project(project["id"])
            )
            self.assertTrue(contexts.metric)
            self.assertTrue(all(key[2] == "IC50 (nM)" for key in contexts.metric))
        self.assertEqual(
            before,
            {
                str(file): hashlib.sha256(file.read_bytes()).hexdigest()
                for file in run.rglob("*")
                if file.is_file()
            },
        )
        self.assertEqual(
            [
                row["activity_sources"][0]["cells"][-1]["value"]
                for row in json.loads(path.read_text())["rows"]
            ],
            ["3", "2"],
        )
