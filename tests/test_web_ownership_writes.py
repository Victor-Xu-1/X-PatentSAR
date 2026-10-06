"""Unchanged ownership polling and slow serialization do not take the writer."""

from __future__ import annotations

import sqlite3
import threading
import unittest
from unittest.mock import patch

from test_web_support import SleepRunner, WebFixture

from patent_sar_extractor.web.job_phases import OwnedPhase
from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.models import JobRequest
from patent_sar_extractor.web.pdf import copy_original
from patent_sar_extractor.web.service import WorkspaceService
from patent_sar_extractor.web.storage import encode


class OwnershipWriteTests(WebFixture, unittest.TestCase):
    def draft(self):
        service = WorkspaceService(self.state)
        project = service.add_pdf(
            copy_original(self.pdf, self.state / "uploads"), "input.pdf", None
        )
        runner = SleepRunner()
        queue = JobQueue(service, runner, 30)
        job = queue.enqueue(project.id, JobRequest())
        spec = decode_spec(service.store.job(job.id)["spec"])
        return service, runner, spec

    def test_unchanged_identity_poll_is_read_only_but_observes_cancellation(self):
        service, runner, spec = self.draft()
        identity = runner.start(spec)
        self.addCleanup(lambda: runner.stop(identity, spec, grace_seconds=0.1))
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='running' WHERE id=?", (spec.job_id,)
            )
        phase = OwnedPhase(service.store, runner, threading.Event())
        with patch.object(
            service.store, "connect", wraps=service.store.connect
        ) as connect:
            self.assertFalse(phase._persist(spec.job_id, identity))
            self.assertFalse(phase._persist(spec.job_id, identity))
        self.assertEqual(
            sum(call.kwargs.get("write", False) for call in connect.call_args_list), 1
        )
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET cancel_requested=1 WHERE id=?", (spec.job_id,)
            )
        with patch.object(
            service.store, "connect", wraps=service.store.connect
        ) as connect:
            self.assertTrue(phase._persist(spec.job_id, identity))
        self.assertTrue(
            all(not call.kwargs.get("write", False) for call in connect.call_args_list)
        )

    def test_projection_serialization_occurs_before_writer_acquisition(self):
        service, _, spec = self.draft()

        def serialize(value):
            with sqlite3.connect(
                service.store.path, timeout=0.05, isolation_level=None
            ) as other:
                other.execute("BEGIN IMMEDIATE")
                other.rollback()
            return encode(value)

        with patch("patent_sar_extractor.web.storage.encode", side_effect=serialize):
            service.store.snapshot(
                spec.project_id,
                {"is_historical": False},
                [
                    {
                        "dto": {"id": "controlled-row"},
                        "image_path": None,
                        "geometry_space": "pdf",
                    },
                ],
                expected_run_root=spec.output_dir,
                expected_sha256=spec.sha256,
            )
        self.assertEqual(
            service.store.compound(spec.project_id, "controlled-row")["payload"],
            '{"id":"controlled-row"}',
        )


if __name__ == "__main__":
    unittest.main()
