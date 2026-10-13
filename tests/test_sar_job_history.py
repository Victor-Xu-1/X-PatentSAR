"""Cross-dataset history uses the retained SAR database and live view authority."""

import unittest
from unittest.mock import patch

import test_sar_api as support
from test_web_support import WebFixture

from patent_sar_extractor.web.sar.engine import engine_identity
from patent_sar_extractor.web.sar.models import SARJob


class SARJobHistoryTests(WebFixture, unittest.TestCase):
    dataset = support.SARAPITests.dataset
    region = support.SARAPITests.region
    completed = support.SARAPITests.completed

    def seed(self, client, dataset, *, status="failed", index=0, title=None):
        identifier = support.nonce()
        job = SARJob(
            id=identifier,
            dataset_id=dataset["id"],
            region_id="",
            metric_id=dataset["metrics"][0]["id"],
            status=status,
            total=3,
            created_at=f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00",
            input_sha256="1" * 64,
            kind="study" if title else "reference",
        )
        # Read-only history fixture: never ready, no process or fabricated report.
        client.app.state.sar_queue.jobs.create(
            job,
            support.nonce(),
            "2" * 64,
            {
                "engine_sha256": engine_identity(),
                "request": {"title": title},
                "attempt_id": support.nonce(),
            },
            str(self.root / "unused-history-fixture" / identifier),
        )
        return job

    def test_empty_history_is_a_read_only_paginated_resource(self):
        with self.client() as client:
            response = client.get(support.ROOT + "/jobs")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(
                response.json(),
                {
                    "items": [],
                    "total": 0,
                    "page": 1,
                    "page_size": 25,
                    "active_count": 0,
                },
            )

    def test_history_uses_the_existing_session_boundary(self):
        with self.client() as client:
            client.cookies.clear()
            response = client.get(support.ROOT + "/jobs")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"]["code"], "session_required")

    def test_cross_dataset_pagination_and_filters_do_not_load_scientific_reports(self):
        with self.client() as client:
            first, second = self.dataset(client), self.dataset(client)
            created = [
                self.seed(
                    client,
                    first if index % 2 else second,
                    index=index,
                    title=f"Study 原文 {index}",
                )
                for index in range(53)
            ]
            queue = client.app.state.sar_queue
            with (
                patch.object(
                    queue,
                    "enqueue",
                    side_effect=AssertionError("history cannot start a task"),
                ),
                patch.object(
                    queue.service.assets,
                    "job_files",
                    side_effect=AssertionError(
                        "unpublished metadata cannot load a report"
                    ),
                ),
            ):
                pages = [
                    client.get(support.ROOT + f"/jobs?page={number}").json()
                    for number in (1, 2, 3)
                ]
            self.assertEqual([len(page["items"]) for page in pages], [25, 25, 3])
            ids = [item["job"]["id"] for page in pages for item in page["items"]]
            self.assertEqual(ids, [job.id for job in reversed(created)])
            self.assertTrue(
                all(page["total"] == 53 and page["active_count"] == 0 for page in pages)
            )
            self.assertEqual(pages[0]["items"][0]["title"], "Study 原文 52")
            filtered = client.get(
                support.ROOT + "/jobs",
                params={
                    "dataset_id": first["id"],
                    "status": "failed",
                    "page_size": 100,
                },
            ).json()
            self.assertEqual(filtered["total"], 26)
            self.assertTrue(
                all(
                    item["job"]["dataset_id"] == first["id"]
                    for item in filtered["items"]
                )
            )
            self.assertEqual(
                client.get(support.ROOT + "/jobs?status=complete").json()["total"], 0
            )

    def test_live_status_stale_view_and_removal_use_existing_authority(self):
        with self.client() as client:
            dataset = self.dataset(client)
            stopped = self.seed(client, dataset, index=0)
            queued = self.seed(client, dataset, status="queued", index=1)
            page = client.get(support.ROOT + "/jobs").json()
            self.assertEqual(page["active_count"], 1)
            for item in page["items"]:
                self.assertEqual(
                    item["job"],
                    client.get(support.ROOT + "/jobs/" + item["job"]["id"]).json(),
                )
            self.assertEqual(
                client.delete(support.ROOT + "/jobs/" + queued.id).status_code, 409
            )
            self.assertEqual(
                client.delete(support.ROOT + "/jobs/" + stopped.id).status_code, 204
            )
            self.assertEqual(client.get(support.ROOT + "/jobs").json()["total"], 1)
            self.assertEqual(
                client.get(support.ROOT + "/datasets/" + dataset["id"]).status_code, 200
            )
            with client.app.state.sar_queue.jobs.store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 2
                )

    def test_hidden_dataset_records_are_not_reintroduced_and_invalid_queries_reject(
        self,
    ):
        with self.client() as client:
            dataset = self.dataset(client)
            self.seed(client, dataset)
            self.assertEqual(
                client.delete(support.ROOT + "/datasets/" + dataset["id"]).status_code,
                204,
            )
            self.assertEqual(client.get(support.ROOT + "/jobs").json()["items"], [])
            for params in [
                {"page": 0},
                {"page": 2049},
                {"page_size": 101},
                {"page_size": 0},
                {"status": "unknown"},
                {"dataset_id": "' OR 1=1 --"},
            ]:
                self.assertEqual(
                    client.get(support.ROOT + "/jobs", params=params).status_code, 422
                )

    def test_native_completed_task_is_listed_with_unmodified_result(self):
        with self.client() as client:
            dataset = self.dataset(client)
            region = self.region(client, dataset)
            response = client.post(
                support.ROOT + "/datasets/" + dataset["id"] + "/jobs",
                json={
                    "request_id": support.nonce(),
                    "expected_dataset_revision": 1,
                    "region_id": region["id"],
                    "metric_id": dataset["metrics"][0]["id"],
                    "direction": "lower",
                    "confirm_context": True,
                },
            )
            self.assertEqual(response.status_code, 202, response.text)
            job = self.completed(client, response.json())
            path = support.ROOT + "/jobs/" + job["id"] + "/export?format=json"
            before = client.get(path).content
            page = client.get(support.ROOT + "/jobs?status=complete").json()
            self.assertEqual(page["total"], 1)
            self.assertEqual(page["items"][0]["job"], job)
            self.assertEqual(page["items"][0]["title"], "IC50 (nM)")
            self.assertEqual(client.get(path).content, before)
