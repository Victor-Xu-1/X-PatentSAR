"""Deletion capabilities use isolated state; no private patent is removed."""

from __future__ import annotations

import hashlib
import json
import unittest
from concurrent.futures import ThreadPoolExecutor

from test_prediction_support import PredictionFixture, controlled_summary

from patent_sar_extractor.web.correction_storage import correction_source_fingerprint
from patent_sar_extractor.web.saved_exports import save_export
from patent_sar_extractor.web.storage import now


class HistoryAPITests(PredictionFixture, unittest.TestCase):
    def entry(self, client, kind, identifier):
        response = client.get(f"/api/v1/history/{kind}/{identifier}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def mutate(self, client, entry, action="delete"):
        return client.post(
            f"/api/v1/history/{entry['kind']}/{entry['id']}/{action}",
            json={"expected_revision": entry["revision"]},
        )

    def terminal_job(self, client, *, core=False):
        service = client.app.state.workspace
        self.service = service
        row, output, _ = self.draft()
        spec = json.loads(row["spec"])
        if core:
            spec.update(admet_only=False, include_admet=False)
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='failed',finished_at=?,spec=? WHERE id=?",
                (now(), json.dumps(spec), row["id"]),
            )
        return service.store.job(row["id"]), output

    def test_project_trash_blocks_every_public_source_path_and_restores_exact_data(
        self,
    ):
        originals = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.run.rglob("*")
            if path.is_file()
        }
        prefix = f"/api/v1/projects/{self.project.id}"
        with self.client() as client:
            self.assertEqual(
                client.put(
                    prefix + "/reviews/Compound%201",
                    json={
                        "decision": "approved",
                        "note": "Keep audit",
                        "expected_revision": 0,
                    },
                ).status_code,
                200,
            )
            before = client.get(prefix).json()
            values = client.get(prefix + "/results").json()["items"]
            entry = self.entry(client, "project", self.project.id)
            removed = self.mutate(client, entry)
            self.assertEqual(removed.status_code, 200, removed.text)
            self.assertIsNotNone(removed.json()["deleted_at"])
            self.assertEqual(self.mutate(client, entry).status_code, 200)
            self.assertEqual(client.get("/api/v1/projects").json()["items"], [])
            for path in (
                prefix,
                prefix + "/results",
                prefix + "/pages/1",
                prefix + "/pages/1/image",
                prefix + "/structures/Compound%201/image",
                prefix + "/structures/Compound%201/redraw",
                prefix + "/structures/Compound%201/correction",
                prefix + "/evidence-summary",
            ):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 404)
            for path, body in (
                (prefix + "/jobs", {}),
                (prefix + "/export", {"format": "json", "compound_ids": []}),
                (prefix + "/compounds/Compound%201/recognize", {}),
            ):
                with self.subTest(path=path):
                    self.assertEqual(client.post(path, json=body).status_code, 404)
            self.assertEqual(
                client.put(
                    prefix + "/reviews/Compound%201",
                    json={
                        "decision": "rejected",
                        "note": "Must not write",
                        "expected_revision": 1,
                    },
                ).status_code,
                404,
            )
            trash = client.get("/api/v1/history?kind=project&deleted=true").json()
            self.assertEqual(trash["total"], 1)
            restored = self.mutate(client, trash["items"][0], "restore")
            self.assertEqual(restored.status_code, 200, restored.text)
            after = client.get(prefix).json()
            self.assertEqual(after, before)
            self.assertEqual(client.get(prefix + "/results").json()["items"], values)
        self.assertEqual(
            originals,
            {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in originals},
        )
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM review_audit").fetchone()[0], 1
            )
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(), []
            )

    def test_removed_producer_job_preserves_current_properties_and_raw_identity(self):
        with self.client() as client:
            row, output = self.terminal_job(client)
            service = client.app.state.workspace
            project = service.store.project(self.project.id)
            raw = service.store.compound(self.project.id, "Compound 1")
            source = correction_source_fingerprint(project, raw)
            service.predictions.put(
                self.project.id,
                "Compound 1",
                controlled_summary(source, "CCO", row["id"]),
            )
            endpoint = f"/api/v1/projects/{self.project.id}/results"
            before = client.get(endpoint).json()["items"]
            self.assertEqual(before[0]["admet"]["status"], "complete")
            removed = self.mutate(client, self.entry(client, "job", row["id"]))
            self.assertEqual(removed.status_code, 200, removed.text)
            self.assertEqual(client.get("/api/v1/jobs").json()["items"], [])
            self.assertEqual(client.get(f"/api/v1/jobs/{row['id']}").status_code, 404)
            self.assertEqual(client.get(endpoint).json()["items"], before)
            self.assertEqual(service.store.job(row["id"]), row)
            self.assertTrue(output.is_dir())
            request = client.post(
                f"/api/v1/projects/{self.project.id}/jobs",
                json={"resume_job_id": row["id"], "include_admet": True},
            )
            self.assertIn(request.status_code, (404, 409), request.text)

    def test_deleting_failed_core_record_cannot_promote_latest_acceptance(self):
        with self.client() as client:
            row, _ = self.terminal_job(client, core=True)
            prefix = f"/api/v1/projects/{self.project.id}"
            before = client.get(prefix).json()
            self.assertEqual(before["acceptance"]["state"], "failed")
            removed = self.mutate(client, self.entry(client, "job", row["id"]))
            self.assertEqual(removed.status_code, 200, removed.text)
            after = client.get(prefix).json()
            self.assertEqual(after["acceptance"], before["acceptance"])
            self.assertIsNone(after["last_job"])

    def test_export_delete_restore_is_persistent_and_parent_guarded(self):
        with self.client() as client:
            service = client.app.state.workspace
            saved = save_export(
                service.store, self.project.id, "csv", [b"Compound,Value\n1,2\n"]
            )
            sha = hashlib.sha256(saved.path.read_bytes()).hexdigest()
            endpoint = f"/api/v1/history?kind=export&project_id={self.project.id}"
            listed = client.get(endpoint)
            self.assertEqual(listed.status_code, 200, listed.text)
            entry = listed.json()["items"][0]
            removed = self.mutate(client, entry)
            self.assertEqual(removed.status_code, 200, removed.text)
            self.assertEqual(client.get(endpoint).json()["total"], 0)
            self.assertEqual(hashlib.sha256(saved.path.read_bytes()).hexdigest(), sha)
            self.assertEqual(
                self.mutate(
                    client, self.entry(client, "project", self.project.id)
                ).status_code,
                200,
            )
            blocked = self.entry(client, "export", entry["id"])
            self.assertFalse(blocked["can_restore"])
            self.assertEqual(self.mutate(client, blocked, "restore").status_code, 409)
            self.assertEqual(
                self.mutate(
                    client, self.entry(client, "project", self.project.id), "restore"
                ).status_code,
                200,
            )
        with self.client() as client:
            retained = self.entry(client, "export", entry["id"])
            self.assertIsNotNone(retained["deleted_at"])
            self.assertEqual(self.mutate(client, retained, "restore").status_code, 200)
            self.assertEqual(client.get(endpoint).json()["total"], 1)
            self.assertEqual(hashlib.sha256(saved.path.read_bytes()).hexdigest(), sha)

    def test_authentication_csrf_validation_and_stale_confirmation(self):
        with self.client() as client:
            entry = self.entry(client, "project", self.project.id)
            stale = {**entry, "revision": "0" * 64}
            self.assertEqual(self.mutate(client, stale).status_code, 409)
            path = f"/api/v1/history/project/{self.project.id}/delete"
            response = client.post(
                path,
                json={"expected_revision": entry["revision"]},
                headers={"X-CSRF-Token": "wrong-token"},
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(client.post(path, json={}).status_code, 422)
            self.assertEqual(
                client.post(
                    path, json={"expected_revision": entry["revision"], "path": "/"}
                ).status_code,
                422,
            )
            for suffix in (
                "?kind=unknown",
                "?kind=project&page=0",
                "?kind=job&page_size=101",
            ):
                self.assertEqual(
                    client.get("/api/v1/history" + suffix).status_code, 422
                )
            self.assertEqual(
                client.get("/api/v1/history/project/not-a-project").status_code, 404
            )
            client.cookies.clear()
            self.assertEqual(
                client.get("/api/v1/history?kind=project").status_code, 401
            )

    def test_real_shared_analysis_lease_blocks_project_delete_without_model_loading(
        self,
    ):
        with self.client() as client:
            entry = self.entry(client, "project", self.project.id)
            with client.app.state.analysis._operation(None):
                checked = self.entry(client, "project", self.project.id)
                self.assertFalse(checked["can_delete"])
                rejected = self.mutate(client, entry)
                self.assertEqual(rejected.status_code, 409, rejected.text)
            self.assertIsNone(
                self.entry(client, "project", self.project.id)["deleted_at"]
            )
            self.assertEqual(self.mutate(client, entry).status_code, 200)

    def test_concurrent_identical_confirmation_has_one_effect_and_rejects_old_cycles(
        self,
    ):
        with self.client() as client, ThreadPoolExecutor(max_workers=2) as pool:
            entry = self.entry(client, "project", self.project.id)
            futures = [pool.submit(self.mutate, client, entry) for _ in range(2)]
            responses = [future.result(timeout=10) for future in futures]
            self.assertEqual(
                [response.status_code for response in responses], [200, 200]
            )
            deleted = responses[0].json()
            self.assertEqual(responses[1].json(), deleted)
            futures = [
                pool.submit(self.mutate, client, deleted, "restore") for _ in range(2)
            ]
            responses = [future.result(timeout=10) for future in futures]
            self.assertEqual(
                [response.status_code for response in responses], [200, 200]
            )
            self.assertEqual(responses[0].json(), responses[1].json())
            # A replay from a previous delete/restore cycle must not remove an
            # item restored with a newer visibility generation.
            self.assertEqual(self.mutate(client, entry).status_code, 409)
