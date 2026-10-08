"""The version-browser setup cannot launch unrelated extraction/model work."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.prepare_browser_fixture import prepare


class ReadOnlyVersionFixtureTests(unittest.TestCase):
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
