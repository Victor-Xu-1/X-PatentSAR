"""Synthetic normal service/HTTP reads; no private document or model task."""

import unittest

from test_sar_api import ROOT
from test_web_support import WebFixture

from tests import test_sar_study_api as support


class DrawingBatchAPITests(WebFixture, unittest.TestCase):
    dataset = support.SARStudyAPITests.dataset
    start = support.SARStudyAPITests.start
    completed = support.SARStudyAPITests.completed

    def test_batch_keeps_job_order_individual_failures_and_existing_single_contract(
        self,
    ):
        with self.client() as client:
            dataset = self.dataset(client, support.CSV)
            job, _ = self.start(client, dataset)
            job = self.completed(client, job)
            path = ROOT + "/jobs/" + job["id"] + "/study"
            rows = client.get(path + "/rows").json()["items"]
            keys = [row["molecule_id"] for row in rows[:2]]
            response = client.get(
                path + "/drawings",
                params=[
                    ("kind", "molecule"),
                    *(("identifier", key) for key in [keys[0], "absent", keys[1]]),
                ],
            )
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result["job"]["id"], job["id"])
            self.assertEqual(result["kind"], "molecule")
            self.assertEqual(result["region_id"], "")
            self.assertEqual(
                [item["identifier"] for item in result["items"]],
                [keys[0], "absent", keys[1]],
            )
            self.assertIsNone(result["items"][1]["result"])
            self.assertIsNotNone(result["items"][1]["error"])
            legacy = client.get(
                path + "/drawing", params={"kind": "molecule", "identifier": keys[0]}
            )
            self.assertEqual(legacy.status_code, 200, legacy.text)
            self.assertEqual(result["items"][0]["result"], legacy.json())

    def test_unbounded_selectors_refuse_before_any_job_lookup(self):
        with self.client() as client:
            path = ROOT + "/jobs/" + "a" * 32 + "/study/drawings"
            for identifiers in ([], ["x"] * 33, ["x", "x"], ["x" * 201]):
                reply = client.get(
                    path,
                    params=[
                        ("kind", "molecule"),
                        *(("identifier", key) for key in identifiers),
                    ],
                )
                self.assertEqual(reply.status_code, 422, reply.text)
