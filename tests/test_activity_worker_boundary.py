"""Actual activity subprocesses on controlled PDFs, never a user patent run."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.application.worker_policy import _run_activity_rules
from tests.test_activity_metadata_native import raster_counts
from tests.test_activity_parser_modules import draw_grid

WORKER_PYTHON = os.environ.get("PATENTSAR_TEST_WORKER_PYTHON") or sys.executable


class ActivityWorkerBoundaryTests(unittest.TestCase):
    def worker_observations(self, document, activity_pages):
        with tempfile.TemporaryDirectory(
            prefix="patentsar-native-table-worker-"
        ) as temporary:
            root = Path(temporary)
            pdf = root / "controlled.pdf"
            document.save(pdf)
            output = root / "observations"
            with patch(
                "patent_sar_extractor.core.env_runner.get_python",
                return_value=WORKER_PYTHON,
            ):
                _run_activity_rules(
                    str(pdf),
                    {
                        "activity_pages": activity_pages,
                        "synthesis_pages": [],
                        "page_count": len(document),
                    },
                    str(output),
                    patent_id="CONTROLLED-WORKER",
                )
            return json.loads((output / "activity_data.json").read_text())

    def native_table(self, rows):
        with fitz.open() as document:
            draw_grid(document.new_page(), rows)
            return self.worker_observations(document, [0])

    def test_native_table_worker_keeps_id_and_metadata_separate(self):
        payload = self.native_table(
            [
                ["No.", "Ki (nM)", "Sample size"],
                ["G-83A", "12.4", "3"],
                ["58", "9.1", "2"],
            ]
        )
        self.assertEqual(
            [row["cpd"] for row in payload["rows"]], ["Compound G-83A", "Compound 58"]
        )
        self.assertEqual(
            [row["activity_values"] for row in payload["rows"]],
            [{"Ki (nM)": "12.4"}, {"Ki (nM)": "9.1"}],
        )
        self.assertTrue(all(not row["needs_review"] for row in payload["rows"]))

    def test_native_missing_neighbor_does_not_shift_endpoint_columns(self):
        payload = self.native_table(
            [["No.", "IC50 (nM)", "Dmax (%)"], ["73", "", "80"]]
        )
        self.assertEqual(
            payload["rows"][0]["activity_values"], {"IC50 (nM)": "", "Dmax (%)": "80"}
        )
        self.assertTrue(payload["rows"][0]["needs_review"])

    def test_native_empty_source_crosses_the_actual_worker_protocol(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((50, 70), "Controlled worker boundary input")
            result = self.worker_observations(document, [])
        self.assertEqual(result["rows"], [])

    def test_raster_table_worker_keeps_metadata_and_ignores_native_footer(self):
        document, _ = raster_counts()
        with document:
            # Keep only the generated scan, not its separate native drawing source.
            document.delete_page(0)
            payload = self.worker_observations(document, [0])
        self.assertEqual(
            [row["cpd"] for row in payload["rows"]], ["Compound 73", "Compound 58"]
        )
        self.assertEqual(
            [row["activity_values"] for row in payload["rows"]],
            [{"IC50 (nM)": "12.4"}, {"IC50 (nM)": "9.1"}],
        )
        self.assertTrue(all(not row["needs_review"] for row in payload["rows"]))
        self.assertEqual(
            [
                row["activity_sources"][0]["cells"][-1]["value"]
                for row in payload["rows"]
            ],
            ["3", "2"],
        )

    def test_raster_worker_preserves_conflicting_native_count_for_review(self):
        document, _ = raster_counts(shadow="4")
        with document:
            document.delete_page(0)
            payload = self.worker_observations(document, [0])
        row = next(row for row in payload["rows"] if row["cpd"] == "Compound 73")
        self.assertEqual(row["activity_values"], {"IC50 (nM)": "12.4"})
        self.assertTrue(row["needs_review"])
        count = row["activity_sources"][0]["cells"][-1]
        self.assertEqual(count["metadata_status"], "unresolved")
        self.assertTrue(
            any(observation["text"] == "4" for observation in count["observations"])
        )
        self.assertTrue(
            any(observation["text"] == "3" for observation in count["observations"])
        )

    def test_actual_worker_failure_keeps_its_terminal_cause_and_publishes_no_rows(self):
        with tempfile.TemporaryDirectory(
            prefix="patentsar-failed-worker-"
        ) as temporary:
            root = Path(temporary)
            output = root / "observations"
            with (
                patch(
                    "patent_sar_extractor.core.env_runner.get_python",
                    return_value=WORKER_PYTHON,
                ),
                self.assertLogs("patent_sar_extractor", level="ERROR") as logs,
                self.assertRaisesRegex(RuntimeError, "FileNotFoundError") as failure,
            ):
                _run_activity_rules(
                    str(root / "missing-control.pdf"),
                    {"activity_pages": [0], "synthesis_pages": [], "page_count": 1},
                    str(output),
                    patent_id="CONTROLLED-FAILURE",
                )
            self.assertIn("FileNotFoundError", logs.output[0])
            self.assertLessEqual(len(str(failure.exception)), 1250)
            self.assertFalse((output / "activity_data.json").exists())


if __name__ == "__main__":
    unittest.main()
