"""Malformed saved results cannot hide independent project identities."""

import hashlib
import json
import unittest
from unittest.mock import patch

from test_web_support import WebFixture, artifact_run

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.project_inputs import project_inputs
from patent_sar_extractor.web.service import WorkspaceService


class ProjectReadIsolationTests(WebFixture, unittest.TestCase):
    def damaged_project(self, field="x" * 301, *, name="damaged"):
        service = WorkspaceService(self.state)
        run = artifact_run(self.root / name, self.pdf, current=False, rows=1)
        project = service.import_run(run, pdf_path=self.pdf, title="Original title")
        path = run / "activity/activity_data.json"
        payload = json.loads(path.read_text())
        payload["rows"][0]["activity_sources"] = [
            {
                "page_no": 1,
                "cells": [{"field": field, "value": "1", "observations": []}],
            }
        ]
        path.write_text(json.dumps(payload))
        with service.store.connect(write=True) as connection:
            raw = service.store.project(project.id)
            snapshot = json.loads(raw["snapshot"])
            snapshot["read_model_identity"] = None
            # Even a previously accepted cache cannot authorize malformed source.
            snapshot["acceptance"] = {"state": "accepted", "errors": []}
            connection.execute(
                "UPDATE projects SET snapshot=? WHERE id=?",
                (json.dumps(snapshot), project.id),
            )
        return service, project, path

    def test_one_invalid_source_keeps_all_project_metadata_visible(self):
        service, damaged, path = self.damaged_project()
        other = artifact_run(self.root / "healthy", self.pdf, current=False, rows=1)
        healthy = service.import_run(other, title="Independent title")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot = service.store.project(damaged.id)["snapshot"]
        with self.client() as client:
            response = client.get("/api/v1/projects")
            self.assertEqual(response.status_code, 200, response.text)
            items = {item["id"]: item for item in response.json()["items"]}
            self.assertEqual(set(items), {damaged.id, healthy.id})
            broken = items[damaged.id]
            self.assertEqual(broken["title"], "Original title")
            self.assertEqual(broken["read_error"]["code"], "invalid_artifact")
            self.assertEqual(broken["acceptance"]["state"], "failed")
            self.assertTrue(broken["is_historical"])
            self.assertIsNone(broken["first_structure_page"])
            self.assertNotIn("read_error", items[healthy.id])
            detail = client.get(f"/api/v1/projects/{damaged.id}")
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(detail.json()["read_error"], broken["read_error"])
            results = client.get(f"/api/v1/projects/{damaged.id}/results")
            self.assertEqual(results.status_code, 422, results.text)
            self.assertEqual(results.json()["error"]["code"], "invalid_artifact")
            self.assertEqual(
                client.get(f"/api/v1/projects/{damaged.id}/pages/1/image").status_code,
                200,
            )
            self.assertEqual(
                client.get(f"/api/v1/projects/{healthy.id}/results").status_code,
                200,
            )
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertEqual(service.store.project(damaged.id)["snapshot"], snapshot)
        with self.assertRaises(WebError) as failure:
            project_inputs(service, damaged.id)
        self.assertEqual(failure.exception.code, "sar_source_unavailable")

    def test_transient_read_issue_is_not_persisted_or_retained_after_a_valid_read(self):
        service, project, path = self.damaged_project()
        self.assertIsNotNone(service.project(project.id).read_error)
        payload = json.loads(path.read_text())
        payload["rows"][0]["activity_sources"][0]["cells"][0]["field"] = "IC50(nM)"
        path.write_text(json.dumps(payload))  # Controlled fixture only.
        reread = service.project(project.id)
        self.assertIsNone(reread.read_error)
        self.assertNotIn("read_error", reread.model_dump())
        self.assertNotIn("read_error", service.store.project(project.id)["snapshot"])

    def test_error_path_rechecks_project_visibility_before_returning_identity(self):
        service = WorkspaceService(self.state)
        with (
            patch.object(
                service,
                "_current_project",
                side_effect=WebError(422, "invalid_artifact", "Saved source invalid"),
            ),
            patch.object(
                service.store,
                "project",
                side_effect=[
                    {"run_root": "retained"},
                    WebError(404, "project_not_found", "No visible project"),
                ],
            ),
            self.assertRaises(WebError) as failure,
        ):
            service.project("a-deleted-project")
        self.assertEqual(failure.exception.status, 404)

    def test_changed_source_during_refusal_is_not_an_old_error_on_new_work(self):
        service = WorkspaceService(self.state)
        with (
            patch.object(
                service,
                "_current_project",
                side_effect=WebError(422, "invalid_artifact", "Old source invalid"),
            ),
            patch.object(
                service.store,
                "project",
                side_effect=[{"run_root": "old"}, {"run_root": "new"}],
            ),
            self.assertRaises(WebError) as failure,
        ):
            service.project("changing-source")
        self.assertEqual(failure.exception.status, 409)
        self.assertEqual(failure.exception.code, "projection_changed")

    def test_nul_and_wrong_type_are_not_repaired_or_truncated(self):
        for index, field in enumerate(("IC50\x00(nM)", 12)):
            with self.subTest(field=field):
                service, project, _ = self.damaged_project(field, name=f"case-{index}")
                metadata = service.project(project.id)
                self.assertEqual(metadata.read_error.code, "invalid_artifact")
                with self.assertRaises(WebError):
                    service._current_project(project.id)

    def test_conflicts_and_unknown_errors_are_not_reclassified_as_saved_data(self):
        service = WorkspaceService(self.state)
        for error in (
            WebError(409, "projection_changed", "Concurrent projection"),
            WebError(404, "project_not_found", "Hidden project"),
            WebError(422, "other_error", "Different contract"),
            RuntimeError("Unexpected implementation failure"),
        ):
            with (
                self.subTest(error=error),
                patch.object(service, "_current_project", side_effect=error),
                patch.object(service.store, "project", return_value={"run_root": None}),
                self.assertRaises(type(error)),
            ):
                service.project("not-an-authorized-project")


if __name__ == "__main__":
    unittest.main()
