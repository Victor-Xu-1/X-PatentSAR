"""Long checkpoint preparation must not monopolize SQLite or start early."""

from __future__ import annotations

import json
import sqlite3
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_web_support import ExitRunner, SleepRunner, WebFixture, wait_job

from patent_sar_extractor.core.page_ocr_cache import build_cache_metadata
from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.models import Error, JobRequest
from patent_sar_extractor.web.pdf import copy_original
from patent_sar_extractor.web.service import WorkspaceService
from patent_sar_extractor.web.storage import now


class JobPreparationTests(WebFixture, unittest.TestCase):
    def origin(self):
        service = WorkspaceService(self.state)
        project = service.add_pdf(
            copy_original(self.pdf, self.state / "uploads"), "input.pdf", None
        )
        queue = JobQueue(service, ExitRunner(), 30)
        job = queue.enqueue(project.id, JobRequest())
        spec = decode_spec(service.store.job(job.id)["spec"])
        cache = {
            "metadata": build_cache_metadata(spec.pdf_path, 1),
            "page_texts": {"0": "partial"},
            "ocr_line_map": {},
        }
        path = Path(spec.output_dir) / "page_classification/page_ocr_cache.json"
        path.parent.mkdir()
        path.write_text(json.dumps(cache))
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='running',started_at=? WHERE id=?",
                (now(), job.id),
            )
        queue._finish(
            job.id,
            "interrupted",
            Error(code="server_interrupted", message="controlled interruption"),
        )
        return service, queue, spec, cache

    def test_slow_checkpoint_copy_returns_durable_queue_before_copy_finishes(self):
        service, queue, original, _ = self.origin()
        entered = threading.Event()
        release = threading.Event()
        returned = threading.Event()
        executed = threading.Event()
        results = []

        def copying(_old, _target, **_kwargs):
            entered.set()
            self.assertTrue(release.wait(5), "controlled copy must be released")

        def submit():
            try:
                results.append(
                    queue.enqueue(
                        original.project_id, JobRequest(resume_job_id=original.job_id)
                    )
                )
            finally:
                returned.set()

        with (
            patch(
                "patent_sar_extractor.web.job_preparation.seed_checkpoints",
                side_effect=copying,
            ),
            patch.object(queue, "_execute", side_effect=lambda _job: executed.set()),
        ):
            queue.start()
            caller = threading.Thread(target=submit)
            caller.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertTrue(
                    returned.wait(1),
                    "the durable queued response must not wait for checkpoint copy",
                )
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].status, "queued")
                self.assertEqual(
                    json.loads(service.store.job(results[0].id)["spec"])[
                        "checkpoint_preparation"
                    ],
                    "preparing",
                )
                self.assertFalse(executed.is_set())
                release.set()
                self.assertTrue(executed.wait(5))
                self.assertEqual(
                    json.loads(service.store.job(results[0].id)["spec"])[
                        "checkpoint_preparation"
                    ],
                    "ready",
                )
            finally:
                release.set()
                caller.join(timeout=5)
                queue.close()

    def test_checkpoint_copy_releases_writer_and_cannot_be_claimed_early(self):
        service, queue, original, _ = self.origin()

        def copying(old, target, **kwargs):
            with sqlite3.connect(
                service.store.path, timeout=0.05, isolation_level=None
            ) as second_writer:
                second_writer.execute("BEGIN IMMEDIATE")
                second_writer.rollback()
            with service.store.connect() as connection:
                row = dict(
                    connection.execute(
                        "SELECT * FROM jobs WHERE status='queued'"
                    ).fetchone()
                )
            self.assertEqual(
                json.loads(row["spec"])["checkpoint_preparation"], "preparing"
            )
            self.assertIsNone(queue._claim_ready())

        with patch(
            "patent_sar_extractor.web.job_preparation.seed_checkpoints",
            side_effect=copying,
        ):
            resumed = queue.enqueue(
                original.project_id, JobRequest(resume_job_id=original.job_id)
            )
            self.assertTrue(queue._prepare_pending())
        self.assertEqual(resumed.status, "queued")
        self.assertEqual(
            json.loads(service.store.job(resumed.id)["spec"])["checkpoint_preparation"],
            "ready",
        )
        claimed = queue._claim_ready()
        self.assertEqual(claimed["id"], resumed.id)

    def test_failed_copy_is_terminal_and_never_starts_the_producer(self):
        service, queue, original, _ = self.origin()
        resumed = queue.enqueue(
            original.project_id, JobRequest(resume_job_id=original.job_id)
        )
        with patch(
            "patent_sar_extractor.web.job_preparation.seed_checkpoints",
            side_effect=OSError("private source path"),
        ):
            self.assertTrue(queue._prepare_pending())
        result = service.job(resumed.id)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error.code, "checkpoint_copy_failed")
        self.assertNotIn("private source path", result.error.message)
        self.assertIsNone(queue._claim_ready())

    def test_unexpected_copy_error_is_contained_in_its_queued_attempt(self):
        service, queue, original, _ = self.origin()
        resumed = queue.enqueue(
            original.project_id, JobRequest(resume_job_id=original.job_id)
        )
        with patch(
            "patent_sar_extractor.web.job_preparation.seed_checkpoints",
            side_effect=RuntimeError("private implementation detail"),
        ):
            self.assertTrue(queue._prepare_pending())
        result = service.job(resumed.id)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error.code, "checkpoint_copy_failed")
        self.assertNotIn("private implementation detail", result.error.message)
        self.assertIsNone(queue._claim_ready())

    def test_http_resume_returns_202_and_guards_duplicate_while_copying(self):
        entered = threading.Event()
        release = threading.Event()

        def copying(_old, _target, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            kwargs["check_cancel"]()

        with self.client(runner=SleepRunner()) as client:
            project = self.upload(client)
            endpoint = f"/api/v1/projects/{project['id']}/jobs"
            original = client.post(endpoint, json={}).json()
            wait_job(client, original["id"], "running")
            client.post(f"/api/v1/jobs/{original['id']}/cancel")
            wait_job(client, original["id"], "cancelled")
            with patch(
                "patent_sar_extractor.web.job_preparation.seed_checkpoints",
                side_effect=copying,
            ):
                try:
                    response = client.post(
                        endpoint, json={"resume_job_id": original["id"]}
                    )
                    self.assertEqual(response.status_code, 202, response.text)
                    resumed = response.json()
                    self.assertEqual(resumed["resume_job_id"], original["id"])
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(
                        client.get(f"/api/v1/jobs/{resumed['id']}").json()["status"],
                        "queued",
                    )
                    self.assertEqual(
                        client.post(
                            endpoint, json={"resume_job_id": original["id"]}
                        ).status_code,
                        409,
                    )
                    self.assertEqual(
                        client.post(f"/api/v1/jobs/{resumed['id']}/cancel").json()[
                            "status"
                        ],
                        "cancelled",
                    )
                finally:
                    release.set()

    def test_changed_checkpoint_owner_fails_without_copying(self):
        service, queue, original, _ = self.origin()
        resumed = queue.enqueue(
            original.project_id, JobRequest(resume_job_id=original.job_id)
        )
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET identity=? WHERE id=?",
                ('{"controlled":true}', original.job_id),
            )
        with patch(
            "patent_sar_extractor.web.job_preparation.seed_checkpoints"
        ) as copying:
            self.assertTrue(queue._prepare_pending())
        copying.assert_not_called()
        result = service.job(resumed.id)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error.code, "checkpoint_source_unavailable")
        self.assertIsNone(queue._claim_ready())

    def test_shutdown_interrupts_copy_and_keeps_original_resumable(self):
        service, queue, original, _ = self.origin()
        entered = threading.Event()
        release = threading.Event()
        close_errors = []

        def copying(_old, _target, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            kwargs["check_cancel"]()

        def close():
            try:
                queue.close()
            except Exception as error:  # noqa: BLE001 - propagate any thread failure to the test
                close_errors.append(error)

        with patch(
            "patent_sar_extractor.web.job_preparation.seed_checkpoints",
            side_effect=copying,
        ):
            queue.start()
            resumed = queue.enqueue(
                original.project_id, JobRequest(resume_job_id=original.job_id)
            )
            self.assertTrue(entered.wait(5))
            closer = threading.Thread(target=close)
            closer.start()
            try:
                self.assertTrue(queue.shutdown.wait(5))
            finally:
                release.set()
                closer.join(timeout=5)
            self.assertFalse(closer.is_alive())
            self.assertEqual(close_errors, [])

        interrupted = service.job(resumed.id)
        self.assertEqual(interrupted.status, "interrupted")
        self.assertEqual(interrupted.error.code, "preparation_interrupted")
        self.assertTrue(interrupted.can_resume)
        self.assertIsNone(queue._claim_ready())
        next_job = queue.enqueue(
            original.project_id, JobRequest(resume_job_id=resumed.id)
        )
        record = json.loads(service.store.job(next_job.id)["spec"])
        self.assertEqual(record["checkpoint_source_job_id"], original.job_id)

    def test_cancel_during_preparation_is_not_overwritten_by_completion(self):
        service, queue, original, _ = self.origin()

        def copying(old, target, **kwargs):
            with service.store.connect() as connection:
                job_id = connection.execute(
                    "SELECT id FROM jobs WHERE status='queued'"
                ).fetchone()[0]
            queue.cancel(job_id)

        with patch(
            "patent_sar_extractor.web.job_preparation.seed_checkpoints",
            side_effect=copying,
        ):
            resumed = queue.enqueue(
                original.project_id, JobRequest(resume_job_id=original.job_id)
            )
            self.assertTrue(queue._prepare_pending())
        self.assertEqual(service.job(resumed.id).status, "cancelled")
        self.assertIsNone(queue._claim_ready())

    def test_restart_during_preparation_resumes_from_declared_original_parent(self):
        service, queue, original, cache = self.origin()

        def crash(old, target, **kwargs):
            raise KeyboardInterrupt("controlled server boundary")

        queue.enqueue(original.project_id, JobRequest(resume_job_id=original.job_id))
        with (
            patch(
                "patent_sar_extractor.web.job_preparation.seed_checkpoints",
                side_effect=crash,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            queue._prepare_pending()
        with service.store.connect() as connection:
            preparing = dict(
                connection.execute(
                    "SELECT * FROM jobs WHERE status='queued'"
                ).fetchone()
            )
        queue.reconcile()
        recovered = service.job(preparing["id"])
        self.assertEqual(recovered.status, "interrupted")
        self.assertEqual(recovered.error.code, "preparation_interrupted")
        self.assertTrue(recovered.can_resume)
        resumed = queue.enqueue(
            original.project_id, JobRequest(resume_job_id=recovered.id)
        )
        self.assertTrue(queue._prepare_pending())
        spec = decode_spec(service.store.job(resumed.id)["spec"])
        new_cache = json.loads(
            (
                Path(spec.output_dir) / "page_classification/page_ocr_cache.json"
            ).read_text()
        )
        self.assertEqual(new_cache, cache)
        record = json.loads(service.store.job(resumed.id)["spec"])
        self.assertEqual(record["checkpoint_source_job_id"], original.job_id)

    def test_preparation_resume_preserves_its_own_options_not_its_source_options(self):
        service, queue, original, _ = self.origin()

        def crash(old, target, **kwargs):
            raise KeyboardInterrupt("controlled server boundary")

        queue.enqueue(
            original.project_id,
            JobRequest(
                include_intermediates=True,
                include_admet=True,
                task_note="retained intention",
            ),
        )
        with (
            patch(
                "patent_sar_extractor.web.job_preparation.seed_checkpoints",
                side_effect=crash,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            queue._prepare_pending()
        with service.store.connect() as connection:
            preparing = dict(
                connection.execute(
                    "SELECT * FROM jobs WHERE status='queued'"
                ).fetchone()
            )
        queue.reconcile()
        resumed = queue.enqueue(
            original.project_id, JobRequest(resume_job_id=preparing["id"])
        )
        self.assertTrue(resumed.include_intermediates)
        self.assertTrue(resumed.include_admet)
        self.assertEqual(resumed.task_note, "retained intention")
        self.assertFalse(resumed.force)


if __name__ == "__main__":
    unittest.main()
