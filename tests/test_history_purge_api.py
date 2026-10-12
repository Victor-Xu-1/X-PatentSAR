"""Authenticated recycle-bin clear contract; only isolated test state."""

import unittest
import uuid

from test_web_support import WebFixture


class HistoryPurgeAPITests(WebFixture, unittest.TestCase):
    def test_authenticated_clear_replay_receipt_and_csrf_with_real_uploaded_file(self):
        with self.client() as client:
            project = self.upload(client)
            entry = client.get("/api/v1/history/project/" + project["id"]).json()
            deleted = client.post(
                "/api/v1/history/project/" + project["id"] + "/delete",
                json={"expected_revision": entry["revision"]},
            )
            self.assertEqual(deleted.status_code, 200, deleted.text)
            plan = client.get("/api/v1/history/trash/plan").json()
            self.assertEqual(plan["files_total"], 1)
            request = {
                "request_id": uuid.uuid4().hex,
                "expected_revision": plan["revision"],
                "expected_total": plan["total"],
            }
            csrf = client.headers.pop("X-CSRF-Token")
            self.assertEqual(
                client.post("/api/v1/history/trash/clear", json=request).status_code,
                403,
            )
            client.headers["X-CSRF-Token"] = csrf
            for invalid in ("1", True, 0, 25001):
                self.assertEqual(
                    client.post(
                        "/api/v1/history/trash/clear",
                        json={**request, "expected_total": invalid},
                    ).status_code,
                    422,
                )
            cleared = client.post("/api/v1/history/trash/clear", json=request)
            self.assertEqual(cleared.status_code, 200, cleared.text)
            receipt = cleared.json()
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(receipt["files_deleted"], 1)
            self.assertEqual(
                client.post("/api/v1/history/trash/clear", json=request).json(), receipt
            )
            self.assertEqual(
                client.get(
                    "/api/v1/history/trash/receipts/" + request["request_id"]
                ).json(),
                receipt,
            )
            self.assertEqual(
                client.get("/api/v1/history?kind=project&deleted=true").json()["total"],
                0,
            )
            self.assertEqual(
                client.get("/api/v1/projects/" + project["id"]).status_code, 404
            )
            self.assertTrue(self.pdf.exists())

    def test_whole_trash_plan_is_not_a_current_page_or_category_count(self):
        with self.client() as client:
            response = client.get("/api/v1/history/trash/plan")
            self.assertEqual(response.status_code, 200, response.text)
            plan = response.json()
            self.assertEqual(plan["total"], sum(plan["counts"].values()))
            self.assertEqual(
                set(plan["counts"]),
                {"project", "job", "export", "environment_operation"},
            )
            self.assertEqual(plan["total"], 0)


if __name__ == "__main__":
    unittest.main()
