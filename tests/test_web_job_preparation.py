"""Long checkpoint preparation must not monopolize SQLite or start early."""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from test_web_support import ExitRunner, WebFixture

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
        self.assertEqual(resumed.status, "queued")
        self.assertEqual(
            json.loads(service.store.job(resumed.id)["spec"])["checkpoint_preparation"],
            "ready",
        )
        claimed = queue._claim_ready()
        self.assertEqual(claimed["id"], resumed.id)

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
        self.assertEqual(resumed.status, "cancelled")
        self.assertIsNone(queue._claim_ready())

    def test_restart_during_preparation_resumes_from_declared_original_parent(self):
        service, queue, original, cache = self.origin()

        def crash(old, target, **kwargs):
            raise KeyboardInterrupt("controlled server boundary")

        with (
            patch(
                "patent_sar_extractor.web.job_preparation.seed_checkpoints",
                side_effect=crash,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            queue.enqueue(
                original.project_id, JobRequest(resume_job_id=original.job_id)
            )
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

        with (
            patch(
                "patent_sar_extractor.web.job_preparation.seed_checkpoints",
                side_effect=crash,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            queue.enqueue(
                original.project_id,
                JobRequest(
                    include_intermediates=True,
                    include_admet=True,
                    task_note="retained intention",
                ),
            )
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
