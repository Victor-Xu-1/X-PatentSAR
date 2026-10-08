"""Copied checkpoints cannot appear before the sole CLI confirms their stages."""

from __future__ import annotations

import hashlib
import json
import unittest
from unittest.mock import patch

from test_web_support import WebFixture, artifact_run

from patent_sar_extractor import contracts as core
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.web.artifacts import ArtifactView
from patent_sar_extractor.web.service import WorkspaceService
from patent_sar_extractor.web.storage import encode


class CheckpointPublicationTests(WebFixture, unittest.TestCase):
    def test_qa_schema_change_rechecks_acceptance_without_rewriting_rows_or_sources(
        self,
    ):
        root = artifact_run(self.root / "qa-schema-history", self.pdf)
        service = WorkspaceService(self.state)
        project = service.import_run(root, pdf_path=self.pdf)
        raw = service.store.project(project.id)
        snapshot = json.loads(raw["snapshot"])
        snapshot["acceptance"] = {"state": "accepted", "errors": []}
        snapshot["core_qa_schema_version"] = 3
        qa_path = root / "final_qa_report.json"
        qa = json.loads(qa_path.read_text())
        qa["schema"]["version"] = 3
        write_json_atomic(qa_path, qa)
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE projects SET snapshot=? WHERE id=?",
                (encode(snapshot), project.id),
            )
            rows_before = connection.execute(
                "SELECT id,payload FROM compounds WHERE project_id=? ORDER BY id",
                (project.id,),
            ).fetchall()
        before = {path: path.read_bytes() for path in root.rglob("*.json")}
        with patch.object(service, "refresh", wraps=service.refresh) as rebuild:
            self.assertEqual(service.project(project.id).acceptance.state, "historical")
            self.assertEqual(service.project(project.id).acceptance.state, "historical")
            rebuild.assert_not_called()
        with service.store.connect() as connection:
            rows_after = connection.execute(
                "SELECT id,payload FROM compounds WHERE project_id=? ORDER BY id",
                (project.id,),
            ).fetchall()
        self.assertEqual(
            [tuple(row) for row in rows_after], [tuple(row) for row in rows_before]
        )
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_rule_change_invalidates_cached_acceptance_and_refreshes_once(self):
        root = artifact_run(self.root / "historical-source", self.pdf, current=False)
        service = WorkspaceService(self.state)
        project = service.import_run(root, pdf_path=self.pdf)
        source_before = {path: path.read_bytes() for path in root.rglob("*.json")}
        with service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE projects SET snapshot=?,historical=0 WHERE id=?",
                (
                    encode(
                        {
                            "acceptance": {"state": "accepted", "errors": []},
                            "summary": {},
                            "read_model_identity": {"old_rules": True},
                        }
                    ),
                    project.id,
                ),
            )
        with patch.object(service, "refresh", wraps=service.refresh) as refresh:
            self.assertEqual(service.project(project.id).acceptance.state, "historical")
            self.assertEqual(service.results(project.id).total, 2)
            self.assertEqual(service.project(project.id).summary.confirmed, 0)
            self.assertEqual(refresh.call_count, 1)
        self.assertEqual(
            {path: path.read_bytes() for path in source_before}, source_before
        )

    def test_current_pending_or_failed_smiles_never_publish_copied_old_chemistry(self):
        root = artifact_run(self.root / "previous-checkpoints", self.pdf)
        for status, stage_status in (("running", "running"), ("failed", "failed")):
            with self.subTest(status=status):
                write_json_atomic(
                    root / "pipeline_summary.json",
                    {
                        **core.artifact_identity(
                            core.RUN_SUMMARY_SCHEMA, core.RUN_SUMMARY_SCHEMA_VERSION
                        ),
                        "status": status,
                        "steps": {
                            "activity": {"status": "ok"},
                            "structures": {"status": "ok"},
                            "bind": {"status": "ok"},
                            "smiles": {"status": stage_status},
                        },
                    },
                )
                snapshot, rows = ArtifactView.read(root).snapshot(
                    "project",
                    pdf_sha256=hashlib.sha256(self.pdf.read_bytes()).hexdigest(),
                )
                self.assertEqual(len(rows), 2)
                self.assertEqual(snapshot["summary"]["matched_structures"], 2)
                self.assertTrue(all(row["dto"]["smiles"] is None for row in rows))
                self.assertTrue(
                    all(row["dto"]["redraw_image_url"] is None for row in rows)
                )
                self.assertFalse(snapshot["acceptance"]["state"] == "accepted")
