"""Targeted ownership/admission/scientific regressions on owned synthetic state."""

from __future__ import annotations

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_sar_api as support
from test_web_support import WebFixture

from patent_sar_extractor.web.analysis_children import alive
from patent_sar_extractor.web.analysis_process import BoundedAnalysisRunner
from patent_sar_extractor.web.analysis_runtime import (
    AnalysisSettings,
    child_environment,
)
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.models import AnalysisRequest, Molecule, Observation
from patent_sar_extractor.workers.sar_worker import _pair


class SARReviewTests(WebFixture, unittest.TestCase):
    dataset = support.SARAPITests.dataset
    region = support.SARAPITests.region

    def submit(self, client, dataset, region):
        return client.post(
            support.ROOT + "/datasets/" + dataset["id"] + "/jobs",
            json={
                "request_id": support.nonce(),
                "expected_dataset_revision": 1,
                "region_id": region["id"],
                "metric_id": dataset["metrics"][0]["id"],
                "direction": "lower",
            },
        )

    def test_resume_cannot_clear_another_unverified_worker_or_remove_its_dataset(self):
        with (
            patch(
                "patent_sar_extractor.web.sar.queue.SARQueue._loop",
                lambda queue: queue.closed.wait(),
            ),
            self.client() as client,
        ):
            first, second = self.dataset(client), self.dataset(client)
            a = self.submit(client, first, self.region(client, first)).json()
            b = self.submit(client, second, self.region(client, second)).json()
            queue = client.app.state.sar_queue
            queue.jobs.update(
                a["id"], status="interrupted", error_code="sar_process_unverified"
            )
            queue.jobs.cancel(b["id"])
            queue.recovery_blocked = True
            with patch("patent_sar_extractor.web.sar.queue.absent", return_value=False):
                response = client.post(
                    support.ROOT + "/jobs/" + b["id"] + "/resume",
                    json={"expected_input_sha256": b["input_sha256"]},
                )
                self.assertEqual(response.status_code, 409, response.text)
            self.assertTrue(queue.recovery_blocked)
            self.assertEqual(queue.jobs.get(b["id"]).status, "cancelled")
            self.assertIsNone(queue.retained_lease)
            self.assertEqual(
                client.delete(support.ROOT + "/datasets/" + first["id"]).status_code,
                409,
            )
            self.assertEqual(
                client.delete(support.ROOT + "/jobs/" + a["id"]).status_code, 409
            )

    def test_denied_fresh_requests_never_publish_uncounted_input_copies(self):
        with (
            patch(
                "patent_sar_extractor.web.sar.queue.SARQueue._loop",
                lambda queue: queue.closed.wait(),
            ),
            self.client() as client,
        ):
            dataset = self.dataset(client)
            region = self.region(client, dataset)
            response = self.submit(client, dataset, region)
            self.assertEqual(response.status_code, 202, response.text)
            queue = client.app.state.sar_queue
            parent = Path(queue.jobs.record(response.json()["id"])["root"]).parent
            before = set(parent.iterdir())
            for _ in range(8):
                self.assertEqual(self.submit(client, dataset, region).status_code, 409)
            self.assertEqual(set(parent.iterdir()), before)
            with queue.service.store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1
                )
                self.assertEqual(
                    connection.execute("SELECT ready FROM jobs").fetchone()[0], 1
                )

    def test_selected_metric_not_affected_by_many_other_endpoint_readings(self):
        context = {
            "target": "T",
            "assay": "binding",
            "cell_line": "not applicable",
            "duration": "1h",
        }
        other = [
            Observation(metric_id="other", value="A", context=context)
            for _ in range(600)
        ]

        def row(identifier, value):
            return Molecule(
                id=identifier,
                label=identifier,
                smiles="CCO",
                molfile="controlled",
                eligible=True,
                observations=[
                    *other,
                    Observation(
                        metric_id="selected", value=value, unit="nM", context=context
                    ),
                ],
            )

        request = AnalysisRequest(
            request_id=support.nonce(),
            expected_dataset_revision=1,
            region_id=support.nonce(),
            metric_id="selected",
            direction="lower",
        )
        matcher = SimpleNamespace(
            compare=lambda _: {"match_status": "matched", "reasons": []}
        )
        pair = _pair(row("a", "10"), row("b", "1"), None, request, matcher)
        self.assertEqual(pair.comparison, "better")
        self.assertEqual(pair.evidence_basis, "recorded_context")
        self.assertEqual(pair.reference_values, ["10"])
        self.assertEqual(pair.fold_change, 10)

    def test_parallel_previews_reserve_all_quotas_before_writing(self):
        with self.client() as client:
            uploads = client.app.state.sar.uploads
            base = uploads.create(support.CSV, "base.csv")
            with uploads.store.connect(write=True) as connection:
                row = connection.execute(
                    "SELECT * FROM uploads WHERE token=?", (base.token,)
                ).fetchone()
                # Only the quota ledger is synthetic; no seed bytes are read.
                connection.executemany(
                    "INSERT INTO uploads VALUES(?,?,?,?,?,?,?)",
                    [
                        (
                            support.nonce(),
                            row["filename"],
                            row["root"],
                            row["sha256"],
                            row["size"],
                            row["preview"],
                            "ready",
                        )
                        for _ in range(30)
                    ],
                )

            def attempt(index):
                try:
                    return uploads.create(support.CSV, f"parallel-{index}.csv")
                except WebError as error:
                    return error.code

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(attempt, range(2)))
            self.assertEqual(outcomes.count("sar_upload_limit"), 1)
            with uploads.store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM uploads").fetchone()[0], 32
                )
            self.assertEqual(len(list(Path(row["root"]).glob("*.csv"))), 2)

    def test_failed_preview_write_stays_counted_and_unreadable(self):
        with self.client() as client:
            uploads = client.app.state.sar.uploads
            with (
                patch(
                    "patent_sar_extractor.web.sar.uploads.atomic_bytes",
                    side_effect=OSError("Controlled disk fault"),
                ),
                self.assertRaises(OSError),
            ):
                uploads.create(support.CSV, "controlled.csv")
            with uploads.store.connect() as connection:
                row = connection.execute("SELECT * FROM uploads").fetchone()
                self.assertEqual(row["status"], "failed")
                self.assertEqual(row["size"], len(support.CSV))
            with self.assertRaises(WebError) as error:
                uploads.read(row["token"])
            self.assertEqual(error.exception.code, "sar_csv_missing")

    def test_prepared_graph_budget_rejects_without_partial_dataset(self):
        with self.client() as client:
            preview = client.post(
                support.ROOT + "/csv/preview?filename=controlled.csv",
                content=support.CSV,
                headers={"Content-Type": "text/csv"},
            ).json()
            with patch(
                "patent_sar_extractor.web.sar.input_records.MAX_DATASET_BYTES", 500
            ):
                response = client.post(
                    support.ROOT + "/datasets/csv",
                    json={
                        "token": preview["token"],
                        "title": "Controlled limit",
                        "id_column": "id",
                        "smiles_column": "smiles",
                        "activity_columns": ["IC50 (nM)"],
                        "request_id": support.nonce(),
                    },
                )
            self.assertEqual(response.status_code, 413, response.text)
            self.assertEqual(client.get(support.ROOT + "/datasets").json()["total"], 0)
            with client.app.state.sar.store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM molecules").fetchone()[0],
                    0,
                )

    def test_callback_failure_before_payload_terminates_only_owned_child(self):
        owned = []

        def refuse(child):
            owned.append(child)
            raise WebError(409, "controlled_ownership", "Controlled pre-input refusal.")

        runner = BoundedAnalysisRunner()
        self.addCleanup(runner.close)
        code = "import sys,pathlib,json; data=sys.stdin.buffer.read(); pathlib.Path('payload.received').write_bytes(data); print(json.dumps({'ok':True,'result':{}}))"
        with self.assertRaises(WebError) as error:
            runner.run(
                [sys.executable, "-I", "-c", code],
                {"controlled": True},
                cwd=self.root,
                env=child_environment(
                    AnalysisSettings(), Path(sys.executable), self.root
                ),
                timeout=3,
                on_start=refuse,
            )
        self.assertEqual(error.exception.code, "controlled_ownership")
        self.assertEqual(len(owned), 1)
        self.assertFalse(alive(owned[0]))
        self.assertFalse((self.root / "payload.received").exists())


if __name__ == "__main__":
    unittest.main()
