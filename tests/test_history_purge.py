"""Atomic all-category trash clearing, with retained originals and producer ancestry."""

import hashlib
import sqlite3
import unittest
import uuid
from unittest.mock import patch

import test_history_deletion as history_support
from test_prediction_support import PredictionFixture

from patent_sar_extractor.web.environment_storage import EnvironmentStore
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.history_guard import history_guard
from patent_sar_extractor.web.history_purge_models import TrashClearRequest
from patent_sar_extractor.web.history_service import HistoryService
from patent_sar_extractor.web.saved_exports import save_export
from patent_sar_extractor.web.storage import now


class HistoryPurgeTests(PredictionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.history = HistoryService(self.service.store)

    def seed(self, count=101):
        with self.service.store.connect(write=True) as connection:
            for _ in range(count):
                identifier = uuid.uuid4().hex
                connection.execute(
                    "INSERT INTO jobs(id,project_id,status,created_at,finished_at,spec) VALUES(?,?,'failed',?,?,'{}')",
                    (identifier, self.project.id, now(), now()),
                )
        saved = save_export(
            self.service.store, self.project.id, "csv", [b"Retained original export\n"]
        )
        self.environment = EnvironmentStore(self.state, self.root / "managed")
        identifier, _ = history_support.EnvironmentHistoryTests.operation(self)
        entry = self.history.get("environment_operation", identifier)
        self.history.delete(entry.kind, entry.id, entry.revision)
        entry = self.history.get("project", self.project.id)
        self.history.delete(entry.kind, entry.id, entry.revision)
        return saved, identifier

    def request(self):
        plan = self.history.trash_plan()
        return TrashClearRequest(
            request_id=uuid.uuid4().hex,
            expected_revision=plan.revision,
            expected_total=plan.total,
        ), plan

    def test_all_types_pages_clear_and_unref_export_removed_while_imported_source_retained(
        self,
    ):
        saved, operation = self.seed()
        pdf = self.pdf
        pdf_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        with self.service.store.connect() as connection:
            before = {
                table: connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in (
                    "projects",
                    "jobs",
                    "compounds",
                    "review_audit",
                    "correction_audit",
                )
            }
        raw_operation = self.environment.row(operation)
        request, plan = self.request()
        self.assertEqual(
            plan.counts,
            {"project": 1, "job": 101, "export": 1, "environment_operation": 1},
        )
        self.assertEqual(
            self.history.list("job", deleted=True, page_size=25).total, 101
        )
        receipt = self.history.clear_trash(request)
        self.assertEqual(receipt.cleared, 104)
        self.assertEqual(receipt.files_deleted, plan.files_total)
        self.assertEqual(receipt.status, "complete")
        for kind in plan.counts:
            self.assertEqual(self.history.list(kind, deleted=True).total, 0)
        self.assertEqual(self.history.clear_receipt(request.request_id), receipt)
        self.assertEqual(self.history.clear_trash(request), receipt)
        self.assertEqual(self.history.trash_plan().total, 0)
        self.assertEqual(pdf_sha, hashlib.sha256(pdf.read_bytes()).hexdigest())
        self.assertFalse(saved.path.exists())
        self.assertTrue(self.run.exists())
        self.assertEqual(raw_operation, self.environment.row(operation))
        with self.service.store.connect() as connection:
            after = {
                table: connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in before
            }
        self.assertEqual(before, after)

    def test_old_restore_and_get_cannot_resurrect_cleared_project_children_or_environment(
        self,
    ):
        _, operation = self.seed(count=2)
        entries = [
            self.history.list(kind, deleted=True).items[0]
            for kind in ("project", "job", "export", "environment_operation")
        ]
        request, _ = self.request()
        self.history.clear_trash(request)
        for entry in entries:
            for call in (self.history.get, self.history.restore):
                with self.assertRaises(WebError) as error:
                    call(
                        entry.kind,
                        entry.id,
                        *([entry.revision] if call == self.history.restore else []),
                    )
                self.assertEqual(error.exception.code, "history_purged")
        self.assertEqual(self.environment.row(operation)["status"], "complete")

    def test_changed_snapshot_refuses_every_write_and_new_nonce_cannot_replay_old_scope(
        self,
    ):
        self.seed(count=2)
        request, _ = self.request()
        entry = self.history.get("project", self.project.id)
        self.history.restore("project", entry.id, entry.revision)
        with self.assertRaises(WebError) as error:
            self.history.clear_trash(request)
        self.assertEqual(error.exception.code, "history_clear_conflict")
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM history_purged_entries"
                ).fetchone()[0],
                0,
            )

    def test_active_or_retained_ownership_blocks_the_complete_batch(self):
        self.seed(count=2)
        request, _ = self.request()
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET identity='unverified' WHERE id=(SELECT id FROM jobs LIMIT 1)"
            )
        plan = self.history.trash_plan()
        self.assertGreater(plan.blocked, 0)
        blocked = request.model_copy(update={"expected_revision": plan.revision})
        with self.assertRaises(WebError) as error:
            self.history.clear_trash(blocked)
        self.assertEqual(error.exception.code, "history_clear_blocked")
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM history_purged_entries"
                ).fetchone()[0],
                0,
            )

    def test_failed_database_publication_rolls_back_marks_and_receipt_across_all_types(
        self,
    ):
        self.seed(count=2)
        request, plan = self.request()
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "CREATE TRIGGER fail_clear BEFORE INSERT ON history_purged_entries WHEN NEW.kind='project' BEGIN SELECT RAISE(ABORT,'controlled failure'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.history.clear_trash(request)
        self.assertEqual(self.history.trash_plan(), plan)
        with self.service.store.connect() as connection:
            for table in ("history_purged_entries", "history_purge_requests"):
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0
                )

    def test_foreign_replay_limits_and_concurrent_history_are_not_silent_success(self):
        self.seed(count=2)
        request, _ = self.request()
        receipt = self.history.clear_trash(request)
        with self.assertRaises(WebError) as error:
            self.history.clear_trash(
                request.model_copy(update={"expected_total": receipt.cleared + 1})
            )
        self.assertEqual(error.exception.code, "history_clear_request_conflict")
        with history_guard(self.state), self.assertRaises(WebError) as error:
            self.history.trash_plan()
        self.assertEqual(error.exception.code, "history_busy")

    def test_complete_inventory_limit_refuses_without_first_page_truncation(self):
        self.seed(count=2)
        with (
            patch("patent_sar_extractor.web.history_trash_plan.MAX_TRASH_RECORDS", 1),
            self.assertRaises(WebError) as error,
        ):
            self.history.trash_plan()
        self.assertEqual(error.exception.code, "history_trash_limit")

    def test_visible_project_and_active_task_are_not_in_the_clear_scope(self):
        self.seed(count=2)
        visible, active = uuid.uuid4().hex, uuid.uuid4().hex
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "INSERT INTO projects(id,title,patent_id,created_at,updated_at) VALUES(?, 'Visible retained project', '', ?, ?)",
                (visible, now(), now()),
            )
            connection.execute(
                "INSERT INTO jobs(id,project_id,status,created_at,spec,identity) VALUES(?,?,'running',?,'{}','retained-active-owner')",
                (active, visible, now()),
            )
        original = self.service.store.job(active)
        request, plan = self.request()
        self.assertEqual(plan.total, 5)
        self.history.clear_trash(request)
        self.assertEqual(self.service.store.job(active), original)
        self.assertEqual(
            self.service.store.project(visible)["title"], "Visible retained project"
        )


if __name__ == "__main__":
    unittest.main()
