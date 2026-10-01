"""Copied checkpoints cannot appear before the sole CLI confirms their stages."""

from __future__ import annotations

import hashlib
import unittest

from patent_sar_extractor import contracts as core
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.web.artifacts import ArtifactView
from test_web_support import WebFixture, artifact_run


class CheckpointPublicationTests(WebFixture, unittest.TestCase):
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
