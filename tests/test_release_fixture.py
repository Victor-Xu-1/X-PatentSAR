"""The version-browser setup cannot launch unrelated extraction/model work."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.browser_fixture_mode import fixture_mode
from tools.prepare_browser_fixture import prepare


class ReadOnlyVersionFixtureTests(unittest.TestCase):
    def test_drawing_batch_uses_only_the_existing_isolated_sar_fixture(self):
        self.assertEqual(
            fixture_mode(
                {
                    "frontend/e2e/sar-drawing-batch.spec.ts",
                    "frontend/e2e/sar-card-inspection.spec.ts",
                }
            ),
            "sar",
        )
        self.assertEqual(
            fixture_mode(
                {
                    "frontend/e2e/sar-drawing-batch.spec.ts",
                    "frontend/e2e/unrelated.spec.ts",
                }
            ),
            "execution",
        )

    def test_label_scope_uses_real_pending_projection_without_models_or_jobs(self):
        from patent_sar_extractor.web.service import WorkspaceService

        self.assertEqual(
            fixture_mode({"frontend/e2e/identifier-labels.spec.ts"}), "llm-settings"
        )
        with (
            tempfile.TemporaryDirectory(prefix="patentsar-label-fixture-") as temporary,
            patch(
                "tools.prepare_browser_fixture.TestClient",
                side_effect=AssertionError("No execution client may start"),
            ),
        ):
            workspace = Path(temporary) / "fixture"
            values = prepare(workspace, llm_settings=True)
            service = WorkspaceService(Path(values["PATENTSAR_WEB_STATE_DIR"]))
            rows = service.compounds(values["PATENTSAR_E2E_HISTORY_PROJECT_ID"])
            pending = [row for row in rows if row.record_kind == "structure_only"]
            self.assertEqual(len(pending), 1)
            self.assertIsNone(pending[0].identifier_label)
            self.assertEqual(pending[0].structure_id, "preview-source")
            self.assertEqual(pending[0].activities, [])
            self.assertIsNone(pending[0].smiles)
            with service.store.connect() as database:
                self.assertEqual(
                    database.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
                )
            self.assertEqual(values["PATENTSAR_E2E_RUN_JOBS"], "0")
            self.assertFalse((service.store.root / "environments").exists())

    def test_real_controlled_setup_contains_no_jobs_or_installer_operations(self):
        with (
            tempfile.TemporaryDirectory(
                prefix="patentsar-version-fixture-"
            ) as temporary,
            patch(
                "tools.prepare_browser_fixture.TestClient",
                side_effect=AssertionError("No execution client may start"),
            ),
        ):
            workspace = Path(temporary) / "fixture"
            values = prepare(workspace, read_only=True)
            self.assertEqual(values["PATENTSAR_E2E_RUN_JOBS"], "0")
            self.assertEqual(
                values["PATENTSAR_E2E_SOURCE_PROJECT_ID"],
                values["PATENTSAR_E2E_HISTORY_PROJECT_ID"],
            )
            with sqlite3.connect(
                Path(values["PATENTSAR_WEB_STATE_DIR"]) / "workspace.sqlite3"
            ) as database:
                self.assertEqual(
                    database.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
                )
                self.assertEqual(
                    database.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1
                )
            self.assertFalse(
                (Path(values["PATENTSAR_WEB_STATE_DIR"]) / "environments").exists()
            )
            self.assertFalse(
                json.loads((workspace / "browser-fixture.json").read_text())[
                    "scientific_acceptance_evidence"
                ]
            )


if __name__ == "__main__":
    unittest.main()
