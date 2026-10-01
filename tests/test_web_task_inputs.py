"""Real upload, queue persistence and CLI contracts for task input."""

from __future__ import annotations

import json
import unittest

from test_web_support import SleepRunner, WebFixture, wait_job

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.page_ocr_cache import build_cache_metadata
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.jobs import decode_spec
from patent_sar_extractor.web.processes import (
    CLIProcessRunner,
    RunSpec,
    runtime_identity,
)
from patent_sar_extractor.web.storage import encode


class TaskInputTests(WebFixture, unittest.TestCase):
    def test_new_run_inherits_only_original_verified_observations_and_keeps_prior_results(
        self,
    ):
        with self.client(runner=SleepRunner()) as client:
            project = self.upload(client)
            endpoint = f"/api/v1/projects/{project['id']}/jobs"
            old = client.post(endpoint, json={}).json()
            client.post(f"/api/v1/jobs/{old['id']}/cancel")
            wait_job(client, old["id"], "cancelled")
            service = client.app.state.workspace
            old_spec = client.app.state.queue._spec(old["id"])
            from pathlib import Path

            root = Path(old_spec.output_dir)
            source = root / "page_classification/page_ocr_cache.json"
            metadata = build_cache_metadata(old_spec.pdf_path)
            metadata["ruleset"]["version"] = "2.0.1"
            metadata.pop("observation_contract")
            write_json_atomic(
                source,
                {
                    "metadata": metadata,
                    "page_texts": {"0": "Original observation"},
                    "ocr_line_map": {},
                },
            )
            before = source.read_bytes()
            response = client.post(endpoint, json={})
            self.assertEqual(response.status_code, 202, response.text)
            fresh = response.json()
            fresh_spec = client.app.state.queue._spec(fresh["id"])
            self.assertNotEqual(fresh_spec.output_dir, old_spec.output_dir)
            self.assertEqual(fresh_spec.source_ocr_cache, str(source))
            self.assertIn("--reuse-ocr-cache", CLIProcessRunner().command(fresh_spec))
            self.assertEqual(source.read_bytes(), before)
            client.post(f"/api/v1/jobs/{fresh['id']}/cancel")
            wait_job(client, fresh["id"], "cancelled")

    def test_duplicate_submission_does_not_create_an_unused_job_directory(self):
        with self.client(runner=SleepRunner()) as client:
            project = self.upload(client)
            endpoint = f"/api/v1/projects/{project['id']}/jobs"
            first_response = client.post(endpoint, json={})
            self.assertEqual(first_response.status_code, 202, first_response.text)
            first = first_response.json()
            root = self.state / "runs" / project["id"]
            before = {path.name for path in root.iterdir()}
            rejected = client.post(endpoint, json={})
            self.assertEqual(rejected.status_code, 409, rejected.text)
            self.assertEqual({path.name for path in root.iterdir()}, before)
            client.post(f"/api/v1/jobs/{first['id']}/cancel")
            wait_job(client, first["id"], "cancelled")

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
