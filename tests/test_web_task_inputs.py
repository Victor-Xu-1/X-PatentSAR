"""Real upload, queue persistence and CLI contracts for task input."""

from __future__ import annotations

import json
import unittest

from test_web_support import SleepRunner, WebFixture, wait_job

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.jobs import decode_spec
from patent_sar_extractor.web.processes import (
    CLIProcessRunner,
    RunSpec,
    runtime_identity,
)
from patent_sar_extractor.web.storage import encode


class TaskInputTests(WebFixture, unittest.TestCase):
    def test_declared_patent_metadata_is_validated_before_upload(self):
        with self.client(runner=SleepRunner()) as client:
            for value in ("../../private", "--force", "WO123\n--output", "X" * 65):
                response = client.post(
                    "/api/v1/projects",
                    params={"filename": "source.pdf", "patent_id": value},
                    content=self.pdf.read_bytes(),
                    headers={"Content-Type": "application/pdf"},
                )
                self.assertEqual(response.status_code, 400, response.text)
            response = client.post(
                "/api/v1/projects",
                params={
                    "filename": "source.pdf",
                    "title": "Declared original",
                    "patent_id": "wo2026/156070",
                },
                content=self.pdf.read_bytes(),
                headers={"Content-Type": "application/pdf"},
            )
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["patent_id"], "WO2026156070")

    def test_real_queue_persists_note_and_options_and_resume_keeps_checkpoints(self):
        with self.client(runner=SleepRunner()) as client:
            project = self.upload(client)
            job = client.post(
                f"/api/v1/projects/{project['id']}/jobs",
                json={
                    "include_intermediates": True,
                    "force": True,
                    "task_note": "  Review activity and source\nKeep strict QA.  ",
                },
            ).json()
            self.assertTrue(job["include_intermediates"])
            self.assertTrue(job["force"])
            self.assertEqual(
                job["task_note"], "Review activity and source\nKeep strict QA."
            )
            persisted = client.get(f"/api/v1/jobs/{job['id']}").json()
            self.assertEqual(persisted["task_note"], job["task_note"])
            client.post(f"/api/v1/jobs/{job['id']}/cancel")
            wait_job(client, job["id"], "cancelled")
            resumed_response = client.post(
                f"/api/v1/projects/{project['id']}/jobs",
                json={"resume_job_id": job["id"], "task_note": "Different note"},
            )
            self.assertEqual(resumed_response.status_code, 202, resumed_response.text)
            resumed = resumed_response.json()
            self.assertTrue(resumed["include_intermediates"])
            self.assertFalse(resumed["force"])
            self.assertEqual(resumed["task_note"], job["task_note"])
            client.post(f"/api/v1/jobs/{resumed['id']}/cancel")
            wait_job(client, resumed["id"], "cancelled")

    def test_request_notes_and_booleans_reject_unsafe_or_ambiguous_values(self):
        with self.client(runner=SleepRunner()) as client:
            project = self.upload(client)
            for body in (
                {"task_note": "x" * 2001},
                {"task_note": "a\x00b"},
                {"task_note": "a\x1bb"},
                {"include_intermediates": "false"},
                {"force": 1},
            ):
                response = client.post(
                    f"/api/v1/projects/{project['id']}/jobs", json=body
                )
                self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(client.get("/api/v1/jobs").json()["items"], [])

    def test_cli_arguments_are_real_flags_and_operator_note_is_not_executed(self):
        spec = RunSpec(
            "j",
            "p",
            "/approved/original.pdf",
            "/approved/output",
            "WO2026156070",
            "sha",
            include_intermediates=True,
            force=True,
            task_note="--allow-partial $(command)",
        )
        command = CLIProcessRunner().command(spec)
        self.assertIn("--include-intermediates", command)
        self.assertIn("--force", command)
        self.assertIn("--skip-advisory-qa", command)
        self.assertNotIn("--allow-partial", command)
        self.assertNotIn(spec.task_note, command)

    def test_prior_job_specs_remain_readable_and_bad_retained_notes_fail(self):
        legacy = {
            "job_id": "j",
            "project_id": "p",
            "pdf_path": "/pdf",
            "output_dir": "/out",
            "patent_id": "WO1",
            "sha256": "sha",
            "allow_partial": False,
            "advisory": False,
            "runtime_identity": runtime_identity(),
        }
        self.assertEqual(decode_spec(encode(legacy)).task_note, "")
        for bad in (42, "\x00", "x" * 2001):
            value = {**legacy, "task_note": bad}
            with self.assertRaisesRegex(WebError, "Persisted job specification"):
                decode_spec(json.dumps(value))
