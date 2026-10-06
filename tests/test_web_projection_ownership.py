"""A delayed old-attempt projection cannot publish after a new enqueue."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from test_web_support import ExitRunner, WebFixture

from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.models import JobRequest
from patent_sar_extractor.web.pdf import copy_original
from patent_sar_extractor.web.service import WorkspaceService


class ProjectionOwnershipTests(WebFixture, unittest.TestCase):
    def draft(self):
        service = WorkspaceService(self.state)
        project = service.add_pdf(
            copy_original(self.pdf, self.state / "uploads"), "input.pdf", None
        )
        queue = JobQueue(service, ExitRunner(), 30)
        job = queue.enqueue(project.id, JobRequest())
        spec = decode_spec(service.store.job(job.id)["spec"])
        with service.store.connect(write=True) as connection:
            connection.execute("UPDATE jobs SET status='failed' WHERE id=?", (job.id,))
        return service, queue, spec

    def test_refresh_loses_ownership_before_publication_and_does_not_restore_acceptance(
        self,
    ):
        service, queue, old = self.draft()

        def read_old_snapshot(*args, **kwargs):
            queue.enqueue(old.project_id, JobRequest(force=True))
            return {"is_historical": False, "acceptance": {"state": "accepted"}}, [
                {
                    "dto": {"id": "old-compound"},
                    "image_path": None,
                    "geometry_space": "pdf",
                }
            ]

        view = SimpleNamespace(root=Path(old.output_dir), snapshot=read_old_snapshot)
        service.refresh(old.project_id, view=view)
        current = service.store.project(old.project_id)
        self.assertNotEqual(current["run_root"], old.output_dir)
        self.assertEqual(
            json.loads(current["snapshot"])["acceptance"]["state"], "not_run"
        )
        with service.store.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM compounds WHERE project_id=?",
                    (old.project_id,),
                ).fetchone()[0],
                0,
            )

    def test_supplied_old_view_is_not_rebound_to_the_new_root(self):
        service, queue, old = self.draft()
        queue.enqueue(old.project_id, JobRequest(force=True))
        read = Mock(
            return_value=(
                {"is_historical": False, "acceptance": {"state": "accepted"}},
                [],
            )
        )
        view = SimpleNamespace(root=Path(old.output_dir), snapshot=read)
        service.refresh(old.project_id, view=view)
        read.assert_not_called()
        self.assertEqual(
            json.loads(service.store.project(old.project_id)["snapshot"])["acceptance"][
                "state"
            ],
            "not_run",
        )


if __name__ == "__main__":
    unittest.main()
