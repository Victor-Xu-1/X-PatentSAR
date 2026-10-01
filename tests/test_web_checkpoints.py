"""Live projections use real SQLite and an owned local process, not accepted chemistry."""

from __future__ import annotations

import time
import unittest
from pathlib import Path

from test_web_support import SleepRunner, WebFixture, wait_job

from patent_sar_extractor import contracts as core
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.page_ocr_cache import build_cache_metadata


class LiveCheckpointTests(WebFixture, unittest.TestCase):
    def test_running_job_exposes_completed_activity_without_formal_acceptance(self):
        with self.client(runner=SleepRunner()) as client:
            project = self.upload(client)
            job = client.post(f"/api/v1/projects/{project['id']}/jobs", json={}).json()
            wait_job(client, job["id"], "running")
            spec = client.app.state.queue._spec(job["id"])
            root = Path(spec.output_dir)
            write_json_atomic(
                root / "page_classification/page_ocr_cache.json",
                {
                    "metadata": build_cache_metadata(spec.pdf_path),
                    "page_texts": {},
                    "ocr_line_map": {},
                },
            )
            write_json_atomic(
                root / "page_classification/page_classification.json",
                {
                    **core.artifact_identity(
                        core.PAGE_CLASSIFICATION_SCHEMA,
                        core.PAGE_CLASSIFICATION_SCHEMA_VERSION,
                    ),
                    "page_count": 1,
                },
            )
            write_json_atomic(
                root / "activity/activity_data.json",
                {
                    **core.artifact_identity(
                        core.ACTIVITY_SCHEMA, core.ACTIVITY_SCHEMA_VERSION
                    ),
                    "active_cpds": ["Compound 31"],
                    "rows": [
                        {
                            "cpd": "Compound 31",
                            "activity_values": {"isolated adapter grade": "A"},
                            "page_no": 1,
                        }
                    ],
                },
            )
            write_json_atomic(
                root / "pipeline_summary.json",
                {
                    **core.artifact_identity(
                        core.RUN_SUMMARY_SCHEMA, core.RUN_SUMMARY_SCHEMA_VERSION
                    ),
                    "status": "running",
                    "steps": {
                        "classify": {"status": "ok"},
                        "activity": {"status": "ok", "rows": 1},
                        "structures": {"status": "running"},
                    },
                },
            )
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                snapshot = client.get(f"/api/v1/projects/{project['id']}").json()
                if snapshot["summary"]["activity_rows"] == 1:
                    break
                time.sleep(0.05)
            self.assertEqual(snapshot["summary"]["activity_rows"], 1)
            self.assertNotEqual(snapshot["acceptance"]["state"], "accepted")
            self.assertEqual(
                client.get(f"/api/v1/jobs/{job['id']}").json()["status"], "running"
            )
            client.post(f"/api/v1/jobs/{job['id']}/cancel")
            wait_job(client, job["id"], "cancelled")
