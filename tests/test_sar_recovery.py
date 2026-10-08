"""Focused SAR restart/source-CAS regressions on disposable controlled state.

Use an explicit PYTHONPATH selecting the controller's source and test helpers.
No extraction, model, LLM, production data or real worker process is used here.
"""

from __future__ import annotations

import json
import os
import sqlite3
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from test_web_support import WebFixture, artifact_run

from patent_sar_extractor.web.analysis_process import BoundedAnalysisRunner
from patent_sar_extractor.web.environment_models import EnvironmentSettingsRequest
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar import project_inputs as project_module
from patent_sar_extractor.web.sar.assets import digest
from patent_sar_extractor.web.sar.models import AnalysisRequest
from patent_sar_extractor.web.sar.queue import SARQueue
from patent_sar_extractor.web.storage import now

ROOT = "/api/v1/sar"
CSV = (
    b"id,smiles,IC50(nM),assay\n"
    b"reference,COc1ccc(Cl)cc1,10,binding\n"
    b"candidate,CCOc1ccc(Cl)cc1,1,binding\n"
)
RETAINED_TABLES = ("datasets", "molecules", "regions", "pairs", "uploads")


def nonce() -> str:
    return uuid.uuid4().hex


def retained_rows(path: Path) -> dict[str, list[tuple]]:
    with closing(sqlite3.connect(path)) as connection:
        return {
            name: connection.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall()
            for name in RETAINED_TABLES
        }


def idle_queue(queue: SARQueue) -> None:
    """Keep lifecycle/readiness real without consuming or launching jobs."""
    queue.closed.wait()


class NoProcessBoundary(BoundedAnalysisRunner):
    """Fault injection for finally/ledger publication, not physical PID proof."""

    def run(self, *args, **kwargs):
        raise WebError(504, "analysis_timeout", "Controlled no-process failure.")


class SARRecoveryTests(WebFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        # All settings writes belong to this test's native temporary workspace.
        environment = patch.dict(
            os.environ,
            {
                "PATENTSAR_DATA_ALLOWED_ROOT": str(self.root),
                "PATENTSAR_ENVIRONMENT_ALLOWED_ROOT": str(self.root / "environments"),
                "PATENTSAR_ENVIRONMENT_ROOT": str(self.root / "environments/managed"),
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        worker = patch.object(SARQueue, "_loop", idle_queue)
        worker.start()
        self.addCleanup(worker.stop)

    def dataset(self, client):
        preview = client.post(
            ROOT + "/csv/preview?filename=controlled.csv",
            content=CSV,
            headers={"Content-Type": "text/csv"},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        response = client.post(
            ROOT + "/datasets/csv",
            json={
                "token": preview.json()["token"],
                "title": "Controlled recovery",
                "id_column": "id",
                "smiles_column": "smiles",
                "activity_columns": ["IC50(nM)"],
                "assay_column": "assay",
                "request_id": nonce(),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def request(self, client, dataset):
        prefix = ROOT + "/datasets/" + dataset["id"]
        response = client.get(prefix + "/molecules")
        self.assertEqual(response.status_code, 200, response.text)
        reference = response.json()["items"][0]
        region = client.post(
            prefix + "/regions",
            json={
                "molecule_id": reference["id"],
                "expected_dataset_revision": dataset["revision"],
                "expected_graph_sha256": reference["graph_sha256"],
                "atom_indices": [0],
            },
        )
        self.assertEqual(region.status_code, 201, region.text)
        return {
            "request_id": nonce(),
            "expected_dataset_revision": dataset["revision"],
            "region_id": region.json()["id"],
            "metric_id": dataset["metrics"][0]["id"],
            "direction": "lower",
            "confirm_context": True,
        }

    def enqueue(self, client, dataset):
        response = client.post(
            ROOT + "/datasets/" + dataset["id"] + "/jobs",
            json=self.request(client, dataset),
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def source_project(self, client, run):
        projects = client.get("/api/v1/projects").json()["items"]
        self.assertEqual(len(projects), 1)
        project = projects[0]
        # A genuine small controlled PDF binds the synthetic artifact source.
        attached = client.post(
            f"/api/v1/projects/{project['id']}/pdf?filename=controlled.pdf",
            content=self.pdf.read_bytes(),
            headers={"Content-Type": "application/pdf"},
        )
        self.assertEqual(attached.status_code, 200, attached.text)
        source = client.app.state.workspace.store.project(project["id"])
        self.assertEqual(source["run_root"], str(run))
        self.assertTrue(source["sha256"])
        self.assertEqual(source["sha256"], source["expected_sha256"])
        return project["id"]

    def change_condition(self, run, cell_line):
        path = run / "activity/activity_data.json"
        payload = json.loads(path.read_text())
        for row in payload["rows"]:
            row["cell_line"] = cell_line
            row["duration"] = "1h"
        # Only this disposable source artifact is intentionally mutated.
        path.write_text(json.dumps(payload))

    def test_started_terminal_crash_window_blocks_start_resume_and_deletion(self):
        original_state = self.state
        try:
            for status in ("failed", "cancelled", "complete"):
                with self.subTest(status=status):
                    self.state = self.root / ("state-" + status)
                    with self.client() as client:
                        dataset, other = self.dataset(client), self.dataset(client)
                        job = self.enqueue(client, dataset)
                        pending = self.enqueue(client, other)
                        queue = client.app.state.sar_queue
                        self.assertEqual(queue.jobs.claim()["id"], job["id"])
                        queue.jobs.cancel(pending["id"])
                        queue.jobs.update(
                            job["id"],
                            status=status,
                            finished_at=now(),
                            processed=job["total"] if status == "complete" else 0,
                            error_code=None
                            if status == "complete"
                            else "analysis_cleanup_failed",
                        )
                        self.assertEqual(
                            queue.jobs.record(job["id"])["cleanup_verified"], 0
                        )
                        # This is the crash window BEFORE error-code recovery marking.
                        self.assertEqual(
                            client.delete(ROOT + "/jobs/" + job["id"]).status_code, 409
                        )
                        self.assertEqual(
                            client.delete(
                                ROOT + "/datasets/" + dataset["id"]
                            ).status_code,
                            409,
                        )
                    with (
                        patch(
                            "patent_sar_extractor.web.sar.queue.absent",
                            return_value=False,
                        ) as proof,
                        self.client() as restarted,
                    ):
                        queue = restarted.app.state.sar_queue
                        proof.assert_called_once()
                        self.assertTrue(queue.recovery_blocked)
                        recovered = queue.jobs.get(job["id"])
                        self.assertEqual(recovered.error_code, "sar_process_unverified")
                        self.assertEqual(
                            queue.jobs.record(job["id"])["cleanup_verified"], 0
                        )
                        self.assertEqual(
                            restarted.post(
                                ROOT + "/jobs/" + pending["id"] + "/resume",
                                json={"expected_input_sha256": pending["input_sha256"]},
                            ).status_code,
                            409,
                        )
                        self.assertTrue(queue.recovery_blocked)
                        self.assertEqual(
                            queue.jobs.get(pending["id"]).status, "cancelled"
                        )
                        self.assertEqual(
                            restarted.post(
                                ROOT + "/datasets/" + other["id"] + "/jobs",
                                json=self.request(restarted, other),
                            ).status_code,
                            409,
                        )
                        self.assertEqual(
                            restarted.delete(
                                ROOT + "/datasets/" + dataset["id"]
                            ).status_code,
                            409,
                        )
        finally:
            self.state = original_state

    def test_finally_publishes_cleanup_and_resume_claim_reset_ledger(self):
        with self.client() as client:
            dataset = self.dataset(client)
            job = self.enqueue(client, dataset)
            queue = client.app.state.sar_queue
            row = queue.jobs.claim()
            with patch(
                "patent_sar_extractor.web.sar.queue.BoundedAnalysisRunner",
                side_effect=NoProcessBoundary,
            ):
                queue._execute(row)
            stopped = queue.jobs.record(job["id"])
            self.assertEqual(stopped["status"], "failed")
            self.assertEqual(stopped["cleanup_verified"], 1)
            old_attempt = json.loads(stopped["spec"])["attempt_id"]
            receipt = Path(stopped["root"]) / f"cleanup-{old_attempt}.json"
            before = receipt.read_bytes()
            queue.resume(job["id"], job["input_sha256"])
            resumed = queue.jobs.record(job["id"])
            self.assertEqual(resumed["cleanup_verified"], 0)
            self.assertNotEqual(json.loads(resumed["spec"])["attempt_id"], old_attempt)
            self.assertEqual(receipt.read_bytes(), before)
            # A stale queued ledger must not survive claim either.
            with queue.service.store.connect(write=True) as connection:
                connection.execute(
                    "UPDATE jobs SET cleanup_verified=1 WHERE id=?", (job["id"],)
                )
            row = queue.jobs.claim()
            self.assertEqual(queue.jobs.record(job["id"])["cleanup_verified"], 0)
            with patch(
                "patent_sar_extractor.web.sar.queue.BoundedAnalysisRunner",
                side_effect=NoProcessBoundary,
            ):
                queue._execute(row)
            self.assertEqual(queue.jobs.record(job["id"])["cleanup_verified"], 1)
            self.assertEqual(
                client.delete(ROOT + "/jobs/" + job["id"]).status_code, 204
            )
            self.assertEqual(
                client.delete(ROOT + "/datasets/" + dataset["id"]).status_code, 204
            )

    def test_activity_only_condition_change_stales_existing_snapshot(self):
        run = artifact_run(self.root / "source", self.pdf, current=True)
        self.change_condition(run, "controlled-A")
        with self.client(import_runs=[run]) as client:
            project_id = self.source_project(client, run)
            response = client.post(
                ROOT + "/datasets/project",
                json={"project_id": project_id, "request_id": nonce()},
            )
            self.assertEqual(response.status_code, 201, response.text)
            dataset = response.json()
            service = client.app.state.sar
            workspace = client.app.state.workspace
            observations = [
                item.model_dump() for item in service.datasets.all(dataset["id"])
            ]
            self.assertEqual(
                observations[0]["observations"][0]["context"]["cell_line"],
                "controlled-A",
            )
            revision = project_module.project_revision(workspace, project_id)
            with workspace.store.connect() as connection:
                before = connection.execute(
                    "SELECT id,payload FROM compounds WHERE project_id=? ORDER BY id",
                    (project_id,),
                ).fetchall()
            self.assertFalse(service.dataset(dataset["id"]).stale)
            self.change_condition(run, "controlled-B")
            self.assertNotEqual(
                project_module.project_revision(workspace, project_id), revision
            )
            with workspace.store.connect() as connection:
                after = connection.execute(
                    "SELECT id,payload FROM compounds WHERE project_id=? ORDER BY id",
                    (project_id,),
                ).fetchall()
            self.assertEqual(
                [tuple(row) for row in before], [tuple(row) for row in after]
            )
            self.assertTrue(service.dataset(dataset["id"]).stale)
            self.assertEqual(
                [item.model_dump() for item in service.datasets.all(dataset["id"])],
                observations,
            )
            with self.assertRaises(WebError) as error:
                service.current(dataset["id"])
            self.assertEqual(error.exception.code, "sar_dataset_stale")

    def test_condition_change_during_snapshot_refuses_partial_publication(self):
        run = artifact_run(self.root / "source", self.pdf, current=True)
        self.change_condition(run, "controlled-A")
        with self.client(import_runs=[run]) as client:
            project_id = self.source_project(client, run)
            original = project_module.ObservationContexts

            for scenario in ("changed_after_read", "ABA"):
                with self.subTest(scenario=scenario):
                    self.change_condition(run, "controlled-A")

                    def mutate_after_read(project, scenario=scenario):
                        if scenario == "ABA":
                            self.change_condition(run, "controlled-B")
                        contexts = original(project)
                        self.change_condition(
                            run, "controlled-A" if scenario == "ABA" else "controlled-B"
                        )
                        return contexts

                    with patch.object(
                        project_module,
                        "ObservationContexts",
                        side_effect=mutate_after_read,
                    ):
                        response = client.post(
                            ROOT + "/datasets/project",
                            json={"project_id": project_id, "request_id": nonce()},
                        )
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(
                        response.json()["error"]["code"], "sar_source_changed"
                    )
                    with client.app.state.sar.store.connect() as connection:
                        for table in ("datasets", "molecules"):
                            count = connection.execute(
                                f"SELECT COUNT(*) FROM {table}"
                            ).fetchone()[0]
                            self.assertEqual(count, 0)

    def test_result_location_change_after_admission_keeps_persisted_root(self):
        with self.client() as client:
            dataset = self.dataset(client)
            request = AnalysisRequest(**self.request(client, dataset))
            queue = client.app.state.sar_queue
            manager = client.app.state.environments
            original_create = queue.jobs.create
            admitted = []
            moved_root = self.root / "moved-results"

            def move_after_admission(*args, **kwargs):
                job = original_create(*args, **kwargs)
                admitted.append(Path(queue.jobs.record(job.id)["root"]))
                settings = manager.settings()
                manager.save_settings(
                    EnvironmentSettingsRequest(
                        install_root=settings.install_root,
                        upload_root=settings.upload_root,
                        result_root=str(moved_root),
                        expected_revision=settings.revision,
                    )
                )
                return job

            with patch.object(queue.jobs, "create", side_effect=move_after_admission):
                job = queue.enqueue(dataset["id"], request)
            self.assertEqual(queue.service.assets.locations.result_root(), moved_root)
            self.assertEqual(len(admitted), 1)
            row = queue.jobs.record(job.id)
            self.assertEqual(Path(row["root"]), admitted[0])
            self.assertEqual(row["ready"], 1)
            packet = json.loads((admitted[0] / "input.json").read_text())
            self.assertEqual(digest(packet), job.input_sha256)
            self.assertEqual(packet["job_id"], job.id)
            self.assertFalse(list(moved_root.rglob("input.json")))
            self.assertEqual(queue.jobs.claim()["root"], str(admitted[0]))

    def test_v1_without_ready_backup_migration_preserves_records_and_verifies_input(
        self,
    ):
        with self.client() as client:
            valid_dataset, invalid_dataset = self.dataset(client), self.dataset(client)
            valid = self.enqueue(client, valid_dataset)
            invalid = self.enqueue(client, invalid_dataset)
            queue = client.app.state.sar_queue
            database = queue.service.store.path
            valid_root = Path(queue.jobs.record(valid["id"])["root"])
            invalid_root = Path(queue.jobs.record(invalid["id"])["root"])
            sealed_input = (valid_root / "input.json").read_bytes()
            # Simulate a corrupt legacy input without changing its recorded SHA.
            (invalid_root / "input.json").write_text("{}")
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("ALTER TABLE jobs DROP COLUMN ready")
            connection.execute("ALTER TABLE jobs DROP COLUMN cleanup_verified")
            connection.execute("PRAGMA user_version=1")
            connection.commit()
            old_jobs = connection.execute(
                "SELECT * FROM jobs ORDER BY rowid"
            ).fetchall()
            old_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(jobs)")
            }
            self.assertNotIn("ready", old_columns)
        retained = retained_rows(database)
        with self.client() as restarted:
            store = restarted.app.state.sar.store
            queue = restarted.app.state.sar_queue
            with store.connect() as connection:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0], 2
                )
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(jobs)")
                }
                self.assertTrue({"ready", "cleanup_verified"}.issubset(columns))
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                )
            self.assertEqual(retained_rows(database), retained)
            self.assertEqual((valid_root / "input.json").read_bytes(), sealed_input)
            good, bad = queue.jobs.record(valid["id"]), queue.jobs.record(invalid["id"])
            self.assertEqual((good["status"], good["ready"]), ("interrupted", 1))
            self.assertEqual((bad["status"], bad["ready"]), ("failed", 0))
            self.assertIsNone(queue.jobs.claim())
            self.assertEqual(
                queue.jobs.get(valid["id"]).input_sha256, valid["input_sha256"]
            )
            self.assertEqual(
                queue.jobs.get(invalid["id"]).error_code, "sar_input_unpublished"
            )
            self.assertEqual(
                restarted.post(
                    ROOT + "/jobs/" + invalid["id"] + "/resume",
                    json={"expected_input_sha256": invalid["input_sha256"]},
                ).status_code,
                409,
            )
            backups = list(store.root.glob("sar-v1-backup-*.sqlite3"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].stat().st_mode & 0o077, 0)
            self.assertEqual(retained_rows(backups[0]), retained)
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(
                    backup.execute("SELECT * FROM jobs ORDER BY rowid").fetchall(),
                    old_jobs,
                )
            resumed = queue.resume(valid["id"], valid["input_sha256"])
            self.assertEqual(resumed.status, "queued")
            self.assertEqual(queue.jobs.record(valid["id"])["cleanup_verified"], 0)
            queue.cancel(valid["id"])
        with self.client() as restarted:
            self.assertEqual(
                len(
                    list(
                        restarted.app.state.sar.store.root.glob(
                            "sar-v1-backup-*.sqlite3"
                        )
                    )
                ),
                1,
            )
            self.assertEqual(retained_rows(database), retained)

    def test_preparing_restart_frees_pending_slots_but_keeps_retention_counts(self):
        with self.client() as client:
            uploads = client.app.state.sar.uploads
            previews = [
                uploads.create(CSV, f"controlled-{index}.csv") for index in range(32)
            ]
            with uploads.store.connect(write=True) as connection:
                connection.execute("UPDATE uploads SET status='preparing'")
                before = tuple(
                    connection.execute(
                        "SELECT COUNT(*),SUM(size) FROM uploads"
                    ).fetchone()
                )
                root = Path(
                    connection.execute("SELECT root FROM uploads LIMIT 1").fetchone()[0]
                )
            originals = {path.name: path.read_bytes() for path in root.glob("*.csv")}
            with self.assertRaises(WebError) as error:
                uploads.create(CSV, "over-pending-limit.csv")
            self.assertEqual(error.exception.code, "sar_upload_limit")
            with self.assertRaises(WebError) as error:
                uploads.remove(previews[0].token)
            self.assertEqual(error.exception.code, "sar_csv_preparing")
        with self.client() as restarted:
            uploads = restarted.app.state.sar.uploads
            with uploads.store.connect() as connection:
                self.assertEqual(
                    tuple(
                        connection.execute(
                            "SELECT COUNT(*),SUM(size) FROM uploads"
                        ).fetchone()
                    ),
                    before,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM uploads WHERE status='failed'"
                    ).fetchone()[0],
                    32,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM uploads WHERE status IN ('preparing','ready')"
                    ).fetchone()[0],
                    0,
                )
            self.assertEqual(
                {path.name: path.read_bytes() for path in root.glob("*.csv")}, originals
            )
            with self.assertRaises(WebError) as error:
                uploads.read(previews[0].token)
            self.assertEqual(error.exception.code, "sar_csv_missing")
            uploads.remove(previews[0].token)
            uploads.create(CSV, "after-restart.csv")
            with uploads.store.connect(write=True) as connection:
                count, size = connection.execute(
                    "SELECT COUNT(*),SUM(size) FROM uploads"
                ).fetchone()
                self.assertEqual((count, size), (before[0] + 1, before[1] + len(CSV)))
                # Fill only the synthetic retention ledger, not 512 MiB of disk.
                connection.execute(
                    "UPDATE uploads SET size=size+? WHERE token=?",
                    (512 * 1024 * 1024 - size, previews[0].token),
                )
            with self.assertRaises(WebError) as error:
                uploads.create(CSV, "over-retention-limit.csv")
            self.assertEqual(error.exception.code, "sar_upload_limit")
            self.assertEqual(len(list(root.glob("*.csv"))), 33)


if __name__ == "__main__":
    unittest.main()
