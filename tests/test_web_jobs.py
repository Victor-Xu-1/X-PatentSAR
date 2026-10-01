from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.models import STAGES, JobRequest
from patent_sar_extractor.web.pdf import copy_original
from patent_sar_extractor.web.processes import CLIProcessRunner
from patent_sar_extractor.web.service import WorkspaceService, import_run
from patent_sar_extractor.web.storage import encode, now
from test_web_support import (
    BASE_URL,
    DetachedRunner,
    ExitRunner,
    SleepRunner,
    WebFixture,
    artifact_run,
    wait_job,
)


def live(pid):
    try:
        return (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[
            1
        ].split()[0] != "Z"
    except FileNotFoundError:
        return False


class JobTests(WebFixture, unittest.TestCase):
    def test_real_subprocess_failure_is_not_formal_acceptance(self):
        with self.client(runner=ExitRunner()) as client:
            project = self.upload(client)
            job = client.post(f"/api/v1/projects/{project['id']}/jobs", json={})
            self.assertEqual(job.status_code, 202)
            result = wait_job(client, job.json()["id"], "failed")
            self.assertEqual(result["error"]["code"], "extraction_failed")
            self.assertIn("7", result["error"]["message"])
            self.assertTrue(result["can_resume"])
            self.assertEqual(
                client.get(f"/api/v1/projects/{project['id']}").json()["acceptance"][
                    "state"
                ],
                "not_run",
            )

    def test_single_consumer_queue_and_idempotent_cancel(self):
        runner = SleepRunner()
        with self.client(runner=runner) as client:
            one = self.upload(client)
            two = self.upload(client)
            prefix = f"/api/v1/projects/{one['id']}/jobs"
            first = client.post(prefix, json={}).json()
            wait_job(client, first["id"], "running")
            self.assertEqual(client.post(prefix, json={}).status_code, 409)
            second = client.post(f"/api/v1/projects/{two['id']}/jobs", json={}).json()
            time.sleep(0.2)
            self.assertEqual(
                client.get(f"/api/v1/jobs/{second['id']}").json()["status"], "queued"
            )
            self.assertEqual(len(runner._children), 1)
            client.post(f"/api/v1/jobs/{second['id']}/cancel")
            self.assertEqual(
                client.get(f"/api/v1/jobs/{second['id']}").json()["status"], "cancelled"
            )
            client.post(f"/api/v1/jobs/{first['id']}/cancel")
            result = wait_job(client, first["id"], "cancelled")
            self.assertTrue(result["can_resume"])
            self.assertEqual(
                client.post(f"/api/v1/jobs/{first['id']}/cancel").json()["status"],
                "cancelled",
            )
        self.assertEqual(runner._children, {})

    def test_timeout_is_real_and_own_process_is_stopped(self):
        runner = SleepRunner()
        with self.client(runner=runner, job_timeout_seconds=0.2) as client:
            project = self.upload(client)
            job = client.post(f"/api/v1/projects/{project['id']}/jobs", json={}).json()
            result = wait_job(client, job["id"], "failed")
            self.assertEqual(result["error"]["code"], "job_timeout")
            self.assertEqual(runner._children, {})

    def test_shutdown_preserves_interruption_and_safe_resume(self):
        with self.client(runner=SleepRunner()) as client:
            project = self.upload(client)
            first = client.post(
                f"/api/v1/projects/{project['id']}/jobs", json={}
            ).json()
            wait_job(client, first["id"], "running")
        with self.client(runner=ExitRunner()) as client:
            interrupted = client.get(f"/api/v1/jobs/{first['id']}").json()
            self.assertEqual(interrupted["status"], "interrupted")
            self.assertTrue(interrupted["can_resume"])
            self.assertEqual(
                client.post(
                    f"/api/v1/projects/{project['id']}/jobs",
                    json={"resume_job_id": first["id"], "advisory": True},
                ).status_code,
                409,
            )
            resumed = client.post(
                f"/api/v1/projects/{project['id']}/jobs",
                json={"resume_job_id": first["id"]},
            )
            self.assertEqual(resumed.status_code, 202, resumed.text)
            wait_job(client, resumed.json()["id"], "failed")
            service = WorkspaceService(self.state)
            self.assertNotEqual(
                decode_spec(service.store.job(first["id"])["spec"]).output_dir,
                decode_spec(service.store.job(resumed.json()["id"])["spec"]).output_dir,
            )

    def test_resume_does_not_promote_the_old_cancelled_stage_history(self):
        from patent_sar_extractor import contracts
        from patent_sar_extractor.artifact_io import write_json_atomic

        with self.client(runner=SleepRunner()) as client:
            project = self.upload(client)
            endpoint = f"/api/v1/projects/{project['id']}/jobs"
            first = client.post(endpoint, json={}).json()
            wait_job(client, first["id"], "running")
            old_root = Path(client.app.state.queue._spec(first["id"]).output_dir)
            summary = {
                **contracts.artifact_identity(
                    contracts.RUN_SUMMARY_SCHEMA, contracts.RUN_SUMMARY_SCHEMA_VERSION
                ),
                "status": "running",
                "steps": {
                    "classify": {"status": "ok", "page_count": 1},
                    "activity": {"status": "running"},
                },
            }
            write_json_atomic(old_root / "pipeline_summary.json", summary)
            client.post(f"/api/v1/jobs/{first['id']}/cancel")
            old = wait_job(client, first["id"], "cancelled")
            original = (old_root / "pipeline_summary.json").read_bytes()
            resumed = client.post(endpoint, json={"resume_job_id": first["id"]}).json()
            new_root = Path(client.app.state.queue._spec(resumed["id"]).output_dir)
            write_json_atomic(
                new_root / "pipeline_summary.json",
                {**summary, "steps": {name: {"status": "ok"} for name in STAGES}},
            )
            persisted = client.get(f"/api/v1/jobs/{first['id']}").json()
            self.assertEqual(persisted["status"], "cancelled")
            self.assertEqual(persisted["stages"], old["stages"])
            self.assertEqual(
                (old_root / "pipeline_summary.json").read_bytes(), original
            )
            client.post(f"/api/v1/jobs/{resumed['id']}/cancel")
            wait_job(client, resumed["id"], "cancelled")

    def test_live_state_owner_prevents_second_recovery_or_cli_import(self):
        runner = SleepRunner()
        with self.client(runner=runner) as client:
            project = self.upload(client)
            job = client.post(f"/api/v1/projects/{project['id']}/jobs", json={}).json()
            wait_job(client, job["id"], "running")
            deadline = time.monotonic() + 3
            while not runner._children and time.monotonic() < deadline:
                time.sleep(0.02)
            pid = next(iter(runner._children))
            with (
                self.assertRaises(WebError),
                TestClient(self.app(runner=SleepRunner()), base_url=BASE_URL),
            ):
                self.fail("Second server must not acquire workspace")
            run = artifact_run(self.root / "run", self.pdf, current=False)
            with self.assertRaises(WebError) as error:
                import_run(self.state, run)
            self.assertEqual(error.exception.code, "workspace_busy")
            self.assertTrue(live(pid))
            self.assertEqual(
                client.get(f"/api/v1/jobs/{job['id']}").json()["status"], "running"
            )

    def test_restart_reconciles_verified_own_live_process(self):
        service = WorkspaceService(self.state)
        project = service.add_pdf(
            copy_original(self.pdf, self.state / "uploads"), "a.pdf", None
        )
        old_runner = SleepRunner()
        queue = JobQueue(service, old_runner, 30)
        job = queue.enqueue(project.id, JobRequest())
        spec = decode_spec(service.store.job(job.id)["spec"])
        identity = old_runner.start(spec)
        self.addCleanup(lambda: old_runner.stop(identity, spec))
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='running',started_at=?,identity=? WHERE id=?",
                (now(), encode(identity.to_dict()), job.id),
            )
        self.assertTrue(live(identity.pid))
        with self.client(runner=SleepRunner()) as client:
            result = client.get(f"/api/v1/jobs/{job.id}").json()
            self.assertEqual(result["status"], "interrupted")
            self.assertTrue(result["can_resume"])
            self.assertFalse(live(identity.pid))

    def test_forged_start_time_cannot_kill_unrelated_local_process(self):
        runner = SleepRunner()
        service = WorkspaceService(self.state)
        project = service.add_pdf(
            copy_original(self.pdf, self.state / "uploads"), "a.pdf", None
        )
        queue = JobQueue(service, runner, 30)
        job = queue.enqueue(project.id, JobRequest())
        spec = decode_spec(service.store.job(job.id)["spec"])
        identity = runner.start(spec)
        self.addCleanup(lambda: runner.stop(identity, spec))
        forged = replace(identity, start_ticks=identity.start_ticks + 1)
        self.assertFalse(runner.owns(forged, spec))
        self.assertFalse(runner.stop(forged, spec, grace_seconds=0))
        self.assertTrue(live(identity.pid))
        self.assertTrue(runner.stop(identity, spec, grace_seconds=0.1))

    def test_recovery_rejects_foreign_workspace_without_signalling_process(self):
        service = WorkspaceService(self.state)
        project = service.add_pdf(
            copy_original(self.pdf, self.state / "uploads"), "a.pdf", None
        )
        old_runner = SleepRunner()
        queue = JobQueue(service, old_runner, 30)
        job = queue.enqueue(project.id, JobRequest())
        original = decode_spec(service.store.job(job.id)["spec"])
        foreign = replace(
            original, output_dir=str(self.root / "different-private-workspace")
        )
        identity = old_runner.start(foreign)
        self.addCleanup(lambda: old_runner.stop(identity, foreign))
        record = json.loads(service.store.job(job.id)["spec"])
        record["output_dir"] = foreign.output_dir
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='running',spec=?,identity=? WHERE id=?",
                (encode(record), encode(identity.to_dict()), job.id),
            )
        with self.client(runner=SleepRunner()) as client:
            result = client.get(f"/api/v1/jobs/{job.id}").json()
            self.assertEqual(result["status"], "interrupted")
            self.assertEqual(result["error"]["code"], "unsafe_job_workspace")
            self.assertFalse(result["can_resume"])
            self.assertTrue(live(identity.pid))

    def test_detached_owned_descendant_cancel_without_touching_other_job(self):
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True
        )
        self.addCleanup(lambda: unrelated.wait(timeout=3))
        self.addCleanup(unrelated.terminate)
        runner = DetachedRunner()
        with self.client(runner=runner) as client:
            project = self.upload(client)
            job = client.post(f"/api/v1/projects/{project['id']}/jobs", json={}).json()
            wait_job(client, job["id"], "running")
            store = WorkspaceService(self.state).store
            deadline = time.monotonic() + 5
            descendants = []
            while time.monotonic() < deadline:
                raw = store.job(job["id"])["identity"]
                descendants = json.loads(raw)["descendants"] if raw else []
                if descendants:
                    break
                time.sleep(0.03)
            self.assertTrue(
                descendants,
                "Actual detached child must be observed before cancellation",
            )
            client.post(f"/api/v1/jobs/{job['id']}/cancel")
            wait_job(client, job["id"], "cancelled")
            self.assertTrue(all(not live(d["pid"]) for d in descendants))
            self.assertIsNone(unrelated.poll())

    def test_cli_runner_contract_cpu_flags_and_no_paid_advisory_default(self):
        with self.client(runner=SleepRunner()) as client:
            project = self.upload(client)
            job = client.post(f"/api/v1/projects/{project['id']}/jobs", json={}).json()
            spec = decode_spec(
                WorkspaceService(self.state).store.job(job["id"])["spec"]
            )
            runner = CLIProcessRunner()
            command = runner.command(spec)
            self.assertIn("--skip-advisory-qa", command)
            self.assertNotIn("--force", command)
            for flag, value in (
                ("--gpu-mode", "off"),
                ("--locate-workers", "1"),
                ("--bind-workers", "1"),
                ("--smiles-workers", "1"),
            ):
                self.assertEqual(command[command.index(flag) + 1], value)
            self.assertEqual(runner.environment(spec)["CUDA_VISIBLE_DEVICES"], "-1")
