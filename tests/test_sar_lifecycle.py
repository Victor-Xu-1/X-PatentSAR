"""Scoped lifecycle mocks plus native resumption; never patent/scientific acceptance."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

import test_sar_api as sar_support
from test_sar_api import ROOT, nonce
from test_web_support import WebFixture

from patent_sar_extractor.web.analysis_process import BoundedAnalysisRunner
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.sar.assets import atomic_json
from patent_sar_extractor.web.sar.ownership import absent


class ControlledBoundary(BoundedAnalysisRunner):
    """Owns no process; isolates queue cancellation while native tests prove RPC."""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()

    def run(self, command, payload, **kwargs):
        self.entered.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if kwargs["cancel"].is_set():
                raise WebError(503, "analysis_cancelled", "Controlled cancellation.")
            time.sleep(0.01)
        raise WebError(504, "analysis_timeout", "Controlled timeout.")


class CheckpointBoundary(BoundedAnalysisRunner):
    """Deliberately interrupts a real graph computation after one sealed chunk."""

    def run(self, command, payload, **kwargs):
        from pathlib import Path

        from patent_sar_extractor.workers import sar_worker

        original = sar_worker._pair
        count = 0

        def interrupted(*args):
            nonlocal count
            count += 1
            if count == 26:
                raise RuntimeError("Controlled checkpoint interruption")
            return original(*args)

        with patch.object(sar_worker, "_pair", side_effect=interrupted):
            return sar_worker.analyse(Path(payload["root"]), payload["input_sha256"])


class SARLifecycleTests(WebFixture, unittest.TestCase):
    dataset = sar_support.SARAPITests.dataset
    region = sar_support.SARAPITests.region
    completed = sar_support.SARAPITests.completed

    def start(self, client, dataset, region):
        response = client.post(
            ROOT + "/datasets/" + dataset["id"] + "/jobs",
            json={
                "request_id": nonce(),
                "expected_dataset_revision": 1,
                "region_id": region["id"],
                "metric_id": dataset["metrics"][0]["id"],
                "direction": "lower",
                "confirm_context": True,
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def stopped(self, client, identifier, expected):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            value = client.get(ROOT + "/jobs/" + identifier).json()
            if value["status"] not in {"queued", "running"}:
                self.assertEqual(value["status"], expected, value)
                while (
                    client.app.state.sar_queue.active_id == identifier
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                return value
            time.sleep(0.02)
        self.fail("Controlled lifecycle operation did not stop")

    def test_cancel_active_delete_guard_and_native_resume_same_input(self):
        boundary = ControlledBoundary()
        with self.client() as client:
            dataset = self.dataset(client)
            region = self.region(client, dataset)
            with patch(
                "patent_sar_extractor.web.sar.queue.BoundedAnalysisRunner",
                return_value=boundary,
            ):
                job = self.start(client, dataset, region)
                self.assertTrue(boundary.entered.wait(2))
                self.assertEqual(
                    client.delete(ROOT + "/datasets/" + dataset["id"]).status_code, 409
                )
                self.assertEqual(
                    client.delete(ROOT + "/jobs/" + job["id"]).status_code, 409
                )
                self.assertEqual(
                    client.post(ROOT + "/jobs/" + job["id"] + "/cancel").status_code,
                    200,
                )
                self.stopped(client, job["id"], "cancelled")
            resumed = client.post(
                ROOT + "/jobs/" + job["id"] + "/resume",
                json={"expected_input_sha256": job["input_sha256"]},
            )
            self.assertEqual(resumed.status_code, 202, resumed.text)
            final = self.completed(client, resumed.json())
            self.assertEqual(final["input_sha256"], job["input_sha256"])
            self.assertEqual(
                client.delete(ROOT + "/jobs/" + job["id"]).status_code, 204
            )
            self.assertEqual(client.get(ROOT + "/jobs/" + job["id"]).status_code, 404)
            self.assertEqual(
                client.get(ROOT + "/jobs/" + job["id"] + "/export").status_code, 404
            )

    def test_native_resume_preserves_sealed_chunk_after_controlled_interruption(self):
        data = b"id,smiles,IC50 (nM),assay\nref,COc1ccc(Cl)cc1,10,binding\n" + b"".join(
            f"v{i},CCOc1ccc(Cl)cc1,1,binding\n".encode() for i in range(51)
        )
        with self.client() as client:
            dataset = self.dataset(client, data)
            region = self.region(client, dataset)
            with patch(
                "patent_sar_extractor.web.sar.queue.BoundedAnalysisRunner",
                return_value=CheckpointBoundary(),
            ):
                job = self.start(client, dataset, region)
                stopped = self.stopped(client, job["id"], "failed")
            self.assertEqual(stopped["processed"], 25)
            root = client.app.state.sar.assets.job_files(
                client.app.state.sar_queue.jobs.record(job["id"])["root"], job["id"]
            ).root
            chunk = root / "chunk-0000.json"
            original = (
                hashlib.sha256(chunk.read_bytes()).hexdigest(),
                chunk.stat().st_mtime_ns,
            )
            resumed = client.post(
                ROOT + "/jobs/" + job["id"] + "/resume",
                json={"expected_input_sha256": job["input_sha256"]},
            )
            self.assertEqual(resumed.status_code, 202, resumed.text)
            final = self.completed(client, resumed.json())
            self.assertEqual(final["processed"], 51)
            self.assertEqual(final["matched"], 51)
            self.assertEqual(
                original,
                (
                    hashlib.sha256(chunk.read_bytes()).hexdigest(),
                    chunk.stat().st_mtime_ns,
                ),
            )

    def test_invalid_sar_database_disables_only_sar_not_extraction_ui(self):
        root = self.state / "sar"
        self.state.mkdir(mode=0o700)
        root.mkdir(mode=0o700)
        database = root / "sar.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA user_version=999")
        os.chmod(database, 0o600)
        with self.client() as client:
            self.assertTrue(client.get("/api/v1/health").json()["ready"])
            self.assertEqual(client.get("/api/v1/projects").status_code, 200)
            self.assertEqual(client.get(ROOT + "/datasets").status_code, 503)

    def test_missing_or_malformed_process_proof_cannot_certify_absence(self):
        root = self.root / "owned"
        root.mkdir(mode=0o700)
        safe = SafeFiles(root)
        self.assertFalse(absent(safe, "a" * 32, "b" * 64, "c" * 32))
        atomic_json(
            root,
            "launch-" + "c" * 32 + ".json",
            {
                "schema": 999,
                "job_id": "a" * 32,
                "input_sha256": "b" * 64,
                "boot_id": "11111111-1111-4111-8111-111111111111",
            },
        )
        self.assertFalse(absent(safe, "a" * 32, "b" * 64, "c" * 32))


if __name__ == "__main__":
    unittest.main()
