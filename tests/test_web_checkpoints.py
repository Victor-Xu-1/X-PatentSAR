"""Live projections use real SQLite and an owned local process, not accepted chemistry."""

from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path

from patent_sar_extractor import contracts as core
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.page_ocr_cache import build_cache_metadata
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.stages import read_progress
from test_web_support import SleepRunner, WebFixture, wait_job


class LiveCheckpointTests(WebFixture, unittest.TestCase):
    def progress_payload(self, **changes):
        return {
            "schema": {"name": "patentsar.stage-progress", "version": 1},
            "stage": "smiles",
            "completed": 3,
            "total": 10,
            "cache_hits": 1,
            "failures": 1,
            "device": "cpu",
            "peak_rss_mb": 128.5,
            **changes,
        }

    def test_real_progress_and_cache_facts_are_visible_and_terminal_history_is_frozen(
        self,
    ):
        with self.client(runner=SleepRunner()) as client:
            project = self.upload(client)
            job = client.post(f"/api/v1/projects/{project['id']}/jobs", json={}).json()
            wait_job(client, job["id"], "running")
            root = Path(client.app.state.queue._spec(job["id"]).output_dir)
            summary = {
                **core.artifact_identity(
                    core.RUN_SUMMARY_SCHEMA, core.RUN_SUMMARY_SCHEMA_VERSION
                ),
                "status": "running",
                "steps": {
                    "classify": {"status": "ok", "from_cache": True},
                    "activity": {"status": "ok", "cache": True},
                    "locate": {"status": "ok", "reused": True},
                    "smiles": {"status": "running"},
                },
            }
            write_json_atomic(root / "pipeline_summary.json", summary)
            write_json_atomic(root / "smiles/progress.json", self.progress_payload())
            result = client.get(f"/api/v1/jobs/{job['id']}").json()
            self.assertTrue(result["history_available"])
            self.assertTrue(
                all(stage["reused_checkpoint"] for stage in result["stages"][:3])
            )
            self.assertFalse(result["stages"][5]["reused_checkpoint"])
            self.assertEqual(
                result["stages"][5]["progress"],
                {
                    key: value
                    for key, value in self.progress_payload().items()
                    if key not in {"schema", "stage"}
                },
            )
            client.post(f"/api/v1/jobs/{job['id']}/cancel")
            terminal = wait_job(client, job["id"], "cancelled")
            write_json_atomic(
                root / "smiles/progress.json", self.progress_payload(completed=10)
            )
            self.assertEqual(client.get(f"/api/v1/jobs/{job['id']}").json(), terminal)

    def test_malformed_oversized_symlink_or_semantically_invalid_progress_is_unavailable(
        self,
    ):
        root = self.root / "progress-run"
        root.mkdir(mode=0o700)
        path = root / "smiles/progress.json"
        cases = [
            {"completed": True},
            {"completed": -1},
            {"completed": "3"},
            {"completed": 11},
            {"total": 1_000_001},
            {"cache_hits": 4},
            {"failures": 4},
            {"device": "cuda"},
            {"peak_rss_mb": -1},
            {"peak_rss_mb": True},
            {"peak_rss_mb": "128"},
            {"peak_rss_mb": float("nan")},
            {"schema": {"name": "patentsar.stage-progress", "version": True}},
            {"stage": "bind"},
            {"extra": "untrusted"},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                write_json_atomic(path, self.progress_payload(**changes))
                self.assertIsNone(read_progress(SafeFiles(root)))
        path.write_bytes(b"{partial")
        self.assertIsNone(read_progress(SafeFiles(root)))
        path.write_bytes(b" " * 8193)
        self.assertIsNone(read_progress(SafeFiles(root)))
        path.unlink()
        outside = self.root / "outside-progress.json"
        write_json_atomic(outside, self.progress_payload())
        path.symlink_to(outside)
        self.assertIsNone(read_progress(SafeFiles(root)))

    def test_atomic_progress_replaces_and_null_metrics_are_read_without_prediction(
        self,
    ):
        root = self.root / "atomic-run"
        root.mkdir(mode=0o700)
        path = root / "smiles/progress.json"
        write_json_atomic(path, self.progress_payload())
        done = threading.Event()
        failures = []

        def writer():
            try:
                for number in range(80):
                    write_json_atomic(
                        path,
                        self.progress_payload(
                            completed=3 + number % 7, device=None, peak_rss_mb=None
                        ),
                    )
            except BaseException as exc:
                failures.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=writer)
        thread.start()
        samples = []
        try:
            while not done.is_set():
                progress = read_progress(SafeFiles(root))
                self.assertIsNotNone(progress)
                samples.append(progress)
        finally:
            thread.join(timeout=5)
        self.assertFalse(failures)
        self.assertTrue(samples)
        self.assertIsNone(read_progress(SafeFiles(root)).device)
        self.assertIsNone(read_progress(SafeFiles(root)).peak_rss_mb)

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
