"""Focused review regressions; controlled state only, no real patent/model call."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import test_sar_api as support
from test_web_support import WebFixture

from patent_sar_extractor.web.analysis_lease import analysis_block
from patent_sar_extractor.web.analysis_process import BoundedAnalysisRunner
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.models import Activity
from patent_sar_extractor.web.sar.assets import atomic_json
from patent_sar_extractor.web.sar.observation_contexts import ObservationContexts


class CleanupFault(BoundedAnalysisRunner):
    fail_cleanup = True

    def run(self, *args, **kwargs):
        raise WebError(
            504, "analysis_timeout", "Controlled transport boundary failure."
        )

    def close(self):
        if self.fail_cleanup:
            raise WebError(
                503, "analysis_cleanup_failed", "Controlled cleanup boundary failure."
            )
        super().close()


class SARGuardTests(WebFixture, unittest.TestCase):
    dataset = support.SARAPITests.dataset
    region = support.SARAPITests.region

    def test_csv_above64k_has_its_exact_upload_budget(self):
        data = b"id,smiles,value,assay\n" + b"".join(
            f"ID{i},CCO,1,controlled binding\n".encode() for i in range(4000)
        )
        self.assertGreater(len(data), 65536)
        with self.client() as client:
            response = client.post(
                support.ROOT + "/csv/preview?filename=large.csv",
                content=data,
                headers={"Content-Type": "text/csv"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["row_count"], 4000)
            self.assertEqual(
                client.post(
                    support.ROOT + "/datasets/csv",
                    content=b"x" * 70000,
                    headers={"Content-Type": "application/json"},
                ).status_code,
                413,
            )

    def test_source_cell_lines_survive_same_value_and_manual_value_edit(self):
        root = self.root / "source"
        root.mkdir(mode=0o700)
        (root / "activity").mkdir(mode=0o700)
        rows = [
            {
                "cpd": "Compound 1",
                "page_no": 1,
                "target": "T",
                "assay": "binding",
                "activity_sources": [
                    {
                        "page_no": 1,
                        "target": "T",
                        "assay": "binding",
                        "cell_line": name,
                        "cells": [
                            {"field": "compound_id", "value": "1"},
                            {"field": "IC50(nM)", "value": "10"},
                        ],
                    }
                    for name in ("A", "B")
                ],
            }
        ]
        atomic_json(root / "activity", "activity_data.json", {"rows": rows})
        contexts = ObservationContexts(
            {
                "run_root": str(root),
                "sha256": "a" * 64,
                "expected_sha256": "a" * 64,
                "page_count": 1,
            }
        )
        activity = Activity(
            name="IC50(nM)", value="10", unit="nM", target="T", assay="binding", page=1
        )
        self.assertEqual(
            {row["cell_line"] for row in contexts.contexts("Compound 1", activity)},
            {"A", "B"},
        )
        activity.value = "9"
        self.assertEqual(
            {row["cell_line"] for row in contexts.contexts("Compound 1", activity)},
            {"A", "B"},
        )

    def test_cleanup_weberror_retains_shared_lease_and_blocks_dataset_removal(self):
        boundary = CleanupFault()
        with self.client() as client:
            dataset = self.dataset(client)
            region = self.region(client, dataset)
            try:
                with patch(
                    "patent_sar_extractor.web.sar.queue.BoundedAnalysisRunner",
                    return_value=boundary,
                ):
                    response = client.post(
                        support.ROOT + "/datasets/" + dataset["id"] + "/jobs",
                        json={
                            "request_id": support.nonce(),
                            "expected_dataset_revision": 1,
                            "region_id": region["id"],
                            "metric_id": dataset["metrics"][0]["id"],
                            "direction": "lower",
                        },
                    )
                    self.assertEqual(response.status_code, 202, response.text)
                    queue = client.app.state.sar_queue
                    deadline = time.monotonic() + 3
                    while queue.retained_lease is None and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertIsNotNone(queue.retained_lease)
                    while queue.active_id is not None and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertIsNotNone(analysis_block(self.state))
                    self.assertEqual(
                        client.delete(
                            support.ROOT + "/datasets/" + dataset["id"]
                        ).status_code,
                        409,
                    )
                    self.assertEqual(
                        client.get(
                            support.ROOT + "/jobs/" + response.json()["id"]
                        ).json()["error_code"],
                        "sar_process_unverified",
                    )
            finally:
                boundary.fail_cleanup = False


if __name__ == "__main__":
    unittest.main()
