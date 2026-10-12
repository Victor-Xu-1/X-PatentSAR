"""Cleared forensic metadata must not exhaust active project/environment quotas."""

import unittest
import uuid

from test_web_support import WebFixture

from patent_sar_extractor.web.environment_storage import EnvironmentStore
from patent_sar_extractor.web.storage import Store, now


class HistoryRetentionTests(WebFixture, unittest.TestCase):
    def test_a_new_upload_works_after_200_permanently_cleared_project_audits(self):
        with self.client() as client:
            store = client.app.state.workspace.store
            identifiers = [uuid.uuid4().hex for _ in range(200)]
            with store.connect(write=True) as connection:
                for identifier in identifiers:
                    connection.execute(
                        "INSERT INTO projects(id,title,patent_id,created_at,updated_at) VALUES(?,'Archived metadata','',?,?)",
                        (identifier, now(), now()),
                    )
                    connection.execute(
                        "INSERT INTO history_tombstones(kind,id,deleted_at) VALUES('project',?,?)",
                        (identifier, now()),
                    )
                    connection.execute(
                        "INSERT INTO history_purged_entries(kind,id,purged_at,request_id) VALUES('project',?,?,?)",
                        (identifier, now(), "a" * 32),
                    )
            uploaded = self.upload(client)
            self.assertEqual(
                client.get("/api/v1/projects/" + uploaded["id"]).status_code, 200
            )
            with store.connect() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                    201,
                )

    def test_a_new_environment_operation_works_after_1000_cleared_operation_audits(
        self,
    ):
        store = Store(self.state)
        environment = EnvironmentStore(self.state, self.root / "managed")
        spec = {
            "schema_version": 1,
            "action": "inspect",
            "component_ids": ["base"],
            "install_root": str(self.root / "managed"),
        }
        first, _ = environment.enqueue("first", "fingerprint", spec, 0)
        environment.update(first.id, status="cancelled", finished_at=now())
        source = environment.row(first.id)
        columns = list(source)
        identifiers = [first.id]
        with environment.connect(write=True) as connection:
            for _ in range(999):
                row = {**source, "id": uuid.uuid4().hex, "request_id": uuid.uuid4().hex}
                identifiers.append(row["id"])
                connection.execute(
                    "INSERT INTO operations("
                    + ",".join(columns)
                    + ") VALUES("
                    + ",".join("?" for _ in columns)
                    + ")",
                    [row[key] for key in columns],
                )
        with store.connect(write=True) as connection:
            connection.executemany(
                "INSERT INTO history_purged_entries(kind,id,purged_at,request_id) VALUES('environment_operation',?,?,?)",
                [(identifier, now(), "a" * 32) for identifier in identifiers],
            )
        operation, created = environment.enqueue(
            "new-after-clear", "different", spec, 0
        )
        self.assertTrue(created)
        self.assertEqual(operation.status, "queued")
        # No app/queue/worker has started. A native inspection is NOT claimed.


if __name__ == "__main__":
    unittest.main()
