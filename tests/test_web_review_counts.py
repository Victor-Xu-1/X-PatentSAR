"""Manual-review read counts never mutate generated extraction summaries."""

from __future__ import annotations

import unittest

from patent_sar_extractor.web.service import WorkspaceService
from patent_sar_extractor.web.storage import now
from test_web_support import WebFixture, artifact_run


class ManualReviewCountTests(WebFixture, unittest.TestCase):
    def test_only_decisions_count_and_needs_review_stays_pending(self):
        run = artifact_run(self.root / "run", self.pdf, rows=3)
        original = {path: path.read_bytes() for path in run.rglob("*.json")}
        service = WorkspaceService(self.state)
        project = service.import_run(run, pdf_path=self.pdf)
        self.assertEqual(project.summary.manually_reviewed, 0)
        self.assertEqual(project.summary.manual_review_pending, 3)
        with service.store.connect(write=True) as connection:
            for compound, decision in (
                ("Compound 1", "approved"),
                ("Compound 2", "rejected"),
                ("Compound 3", "needs_review"),
            ):
                connection.execute(
                    "INSERT INTO reviews VALUES(?,?,?,?,?,?)",
                    (project.id, compound, decision, "Operator note", 1, now()),
                )
        result = service.project(project.id)
        self.assertEqual(result.summary.manually_reviewed, 2)
        self.assertEqual(result.summary.manual_review_pending, 1)
        self.assertEqual({path: path.read_bytes() for path in original}, original)
        self.assertEqual(
            WorkspaceService(self.state).project(project.id).summary,
            result.summary,
        )

    def test_empty_compound_set_has_zero_manual_counts(self):
        run = artifact_run(self.root / "empty-run", self.pdf, rows=0)
        project = WorkspaceService(self.state).import_run(run, pdf_path=self.pdf)
        self.assertEqual(project.summary.manually_reviewed, 0)
        self.assertEqual(project.summary.manual_review_pending, 0)
