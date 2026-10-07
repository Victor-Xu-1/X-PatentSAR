"""Recoverable visibility, real SQLite compatibility and retained evidence."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_prediction_support import PredictionFixture, controlled_summary

from patent_sar_extractor.web.analysis import AnalysisService
from patent_sar_extractor.web.analysis_runtime import AnalysisSettings
from patent_sar_extractor.web.correction_models import CorrectionRequest
from patent_sar_extractor.web.environment_cleanup import environment_cleanup_block
from patent_sar_extractor.web.environment_models import COMPONENT_IDS
from patent_sar_extractor.web.environment_process import EnvironmentProcessRunner
from patent_sar_extractor.web.environment_records import environment_spec
from patent_sar_extractor.web.environment_storage import EnvironmentStore
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.files import private_directory
from patent_sar_extractor.web.history_service import HistoryService
from patent_sar_extractor.web.saved_exports import export_bytes, save_export
from patent_sar_extractor.web.storage import Store, encode, now


class HistoryDeletionTests(PredictionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.history = HistoryService(self.service.store)

    def test_project_delete_retains_bytes_and_restore_keeps_identity(self):
        before = self.service.store.project(self.project.id)
        pdf = self.service.store.locations.pdf_path(before)
        original = hashlib.sha256(pdf.read_bytes()).hexdigest()
        metadata = self.history.get("project", self.project.id)
        deleted = self.history.delete("project", self.project.id, metadata.revision)
        self.assertIsNotNone(deleted.deleted_at)
        self.assertEqual(self.service.project_ids(), [])
        with self.assertRaises(WebError) as error:
            self.service.project(self.project.id)
        self.assertEqual(error.exception.status, 404)
        self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), original)
        restored = self.history.restore("project", self.project.id, deleted.revision)
        self.assertIsNone(restored.deleted_at)
        self.assertEqual(self.service.store.project(self.project.id), before)

    def test_history_get_never_rebuilds_projection(self):
        with (
            patch.object(
                self.service, "refresh", side_effect=AssertionError("refresh")
            ),
            patch.object(
                self.service,
                "_current_project",
                side_effect=AssertionError("projection"),
            ),
        ):
            entry = self.history.get("project", self.project.id)
            listing = self.history.list("project")
        self.assertEqual(entry.id, self.project.id)
        self.assertEqual(listing.total, 1)

    def test_export_trash_does_not_move_or_erase_saved_bytes(self):
        saved = save_export(self.service.store, self.project.id, "csv", [b"x,y\n1,2\n"])
        entry = self.history.list("export").items[0]
        deleted = self.history.delete("export", entry.id, entry.revision)
        self.assertEqual(saved.path.read_bytes(), b"x,y\n1,2\n")
        self.assertEqual(self.history.list("export").total, 0)
        self.assertEqual(self.history.list("export", deleted=True).total, 1)
        self.history.restore("export", entry.id, deleted.revision)
        self.assertEqual(self.history.list("export").items[0].id, entry.id)

    def test_export_stream_checks_once_and_already_open_stream_can_finish(self):
        content = b"x" * (128 * 1024)
        saved = save_export(self.service.store, self.project.id, "csv", [content])
        stream = export_bytes(saved)
        first = next(stream)
        entry = self.history.list("export").items[0]
        self.history.delete("export", entry.id, entry.revision)
        with patch.object(
            self.service.store,
            "connect",
            side_effect=AssertionError("per-chunk SQLite"),
        ):
            rest = b"".join(stream)
        self.assertEqual(first + rest, content)
        with self.assertRaises(WebError) as error:
            b"".join(export_bytes(saved))
        self.assertEqual(error.exception.status, 404)

    def test_export_publication_rechecks_project_trash_and_keeps_old_files(self):
        retained = save_export(self.service.store, self.project.id, "json", [b"{}"])
        before = {
            path.name: path.read_bytes() for path in retained.path.parent.iterdir()
        }

        def racing_content():
            entry = self.history.get("project", self.project.id)
            self.history.delete("project", self.project.id, entry.revision)
            yield b"must not publish a new export"

        with self.assertRaises(WebError) as error:
            save_export(self.service.store, self.project.id, "csv", racing_content())
        self.assertEqual(error.exception.status, 404)
        self.assertEqual(
            {path.name: path.read_bytes() for path in retained.path.parent.iterdir()},
            before,
        )
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM history_exports").fetchone()[
                    0
                ],
                1,
            )

    def test_active_or_retained_identity_blocks_project_and_job_delete(self):
        row, _, _ = self.draft()
        for kind, identifier in (("project", self.project.id), ("job", row["id"])):
            entry = self.history.get(kind, identifier)
            self.assertFalse(entry.can_delete)
            with self.assertRaises(WebError) as error:
                self.history.delete(kind, identifier, entry.revision)
            self.assertEqual(error.exception.status, 409)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='interrupted',identity='{}' WHERE id=?",
                (row["id"],),
            )
        self.assertFalse(self.history.get("project", self.project.id).can_delete)
        self.assertFalse(self.history.get("job", row["id"]).can_delete)

    def test_job_deletion_does_not_remove_raw_producer_or_promote_acceptance(self):
        row, _, _ = self.draft()
        spec = json.loads(row["spec"])
        spec.update(admet_only=False, include_admet=False)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='failed',spec=? WHERE id=?",
                (json.dumps(spec), row["id"]),
            )
        before = self.service.project(self.project.id).acceptance
        self.assertEqual(before.state, "failed")
        entry = self.history.get("job", row["id"])
        self.history.delete("job", row["id"], entry.revision)
        self.assertEqual(self.service.store.job(row["id"])["status"], "failed")
        project = self.service.project(self.project.id)
        self.assertIsNone(project.last_job)
        self.assertEqual(project.acceptance, before)

    def test_terminal_admet_producer_can_be_hidden_without_losing_current_properties(
        self,
    ):
        row, output, source = self.draft()
        self.service.predictions.put(
            self.project.id, "Compound 1", controlled_summary(source, "CCO", row["id"])
        )
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='failed',finished_at=? WHERE id=?",
                (now(), row["id"]),
            )
        retained = self.service.store.job(row["id"])
        before = self.service.results(self.project.id)
        self.assertEqual(before.items[0].admet.status, "complete")
        entry = self.history.get("job", row["id"])
        self.assertIn(self.project.title, entry.title)
        self.history.delete("job", row["id"], entry.revision)
        self.assertEqual(self.service.results(self.project.id), before)
        self.assertEqual(self.service.store.job(row["id"]), retained)
        self.assertTrue(output.is_dir())

    def test_export_root_marker_stays_authority_and_unknown_files_are_not_adopted(self):
        from patent_sar_extractor.web.data_location_policy import MARKER

        environment = EnvironmentStore(self.state, self.root / "managed")
        root = self.root / "managed-results"
        environment.save_settings(
            self.root / "managed",
            0,
            upload_root=str(self.root / "managed-uploads"),
            result_root=str(root),
        )
        saved = save_export(
            self.service.store, self.project.id, "csv", [b"retained bytes"]
        )
        entry = self.history.list("export").items[0]
        self.assertIn(self.project.title, entry.title)
        deleted = self.history.delete("export", entry.id, entry.revision)
        marker = root / MARKER
        original_marker = marker.read_bytes()
        marker.write_bytes(
            b"{}"
        )  # Simulate changed ownership only in this disposable root.
        unknown = saved.path.parent / ("b" * 32 + ".json")
        unknown.write_bytes(b"must not adopt")
        unavailable = self.history.get("export", entry.id)
        self.assertEqual(unavailable.status, "unavailable")
        self.assertFalse(unavailable.can_restore)
        self.assertIn("ownership", unavailable.blocked_reason)
        self.assertEqual(self.history.list("export", deleted=True).total, 1)
        self.assertEqual(self.history.list("export").total, 0)
        with self.assertRaises(WebError):
            self.history.restore("export", entry.id, unavailable.revision)
        self.assertEqual(saved.path.read_bytes(), b"retained bytes")
        self.assertEqual(unknown.read_bytes(), b"must not adopt")
        marker.write_bytes(original_marker)
        self.history.restore("export", entry.id, deleted.revision)
        self.assertEqual(self.history.list("export").total, 2)

    def test_replays_are_idempotent_but_old_confirmation_is_not_reused_after_restore(
        self,
    ):
        entry = self.history.get("project", self.project.id)
        deleted = self.history.delete("project", self.project.id, entry.revision)
        self.assertEqual(
            self.history.delete("project", self.project.id, entry.revision), deleted
        )
        restored = self.history.restore("project", self.project.id, deleted.revision)
        self.assertEqual(
            self.history.restore("project", self.project.id, deleted.revision), restored
        )
        with self.assertRaises(WebError) as error:
            self.history.delete("project", self.project.id, entry.revision)
        self.assertEqual(error.exception.code, "history_conflict")
        self.assertEqual(self.service.project_ids(), [self.project.id])

    def test_parent_restore_preserves_individually_deleted_children(self):
        first = save_export(self.service.store, self.project.id, "json", [b"{}"])
        second = save_export(self.service.store, self.project.id, "csv", [b"x\n1\n"])
        entries = self.history.list("export").items
        individual = next(entry for entry in entries if entry.size_bytes == first.size)
        self.history.delete("export", individual.id, individual.revision)
        project = self.history.get("project", self.project.id)
        deleted_project = self.history.delete(
            "project", self.project.id, project.revision
        )
        self.assertEqual(self.history.list("export").total, 0)
        self.assertEqual(self.history.list("export", deleted=True).total, 2)
        for child in self.history.list("export", deleted=True).items:
            self.assertFalse(child.can_restore)
            with self.assertRaises(WebError) as error:
                self.history.restore("export", child.id, child.revision)
            self.assertEqual(error.exception.code, "history_parent_deleted")
        self.history.restore("project", self.project.id, deleted_project.revision)
        self.assertEqual(self.history.list("export").total, 1)
        self.assertEqual(self.history.list("export", deleted=True).total, 1)
        self.assertEqual(first.path.read_bytes(), b"{}")
        self.assertEqual(second.path.read_bytes(), b"x\n1\n")
        with self.assertRaises(WebError):
            b"".join(export_bytes(first))
        self.assertEqual(b"".join(export_bytes(second)), b"x\n1\n")

    def test_missing_export_is_truthful_and_cannot_be_restored(self):
        saved = save_export(self.service.store, self.project.id, "json", [b"{}"])
        entry = self.history.list("export").items[0]
        self.history.delete("export", entry.id, entry.revision)
        saved.path.unlink()  # This test's exclusive disposable file, never user data.
        missing = self.history.get("export", entry.id)
        self.assertEqual(missing.status, "missing")
        self.assertFalse(missing.can_restore)
        self.assertIn("missing", missing.blocked_reason)
        with self.assertRaises(WebError) as error:
            self.history.restore("export", entry.id, missing.revision)
        self.assertEqual(error.exception.code, "history_blocked")

    def test_export_discovery_is_direct_owned_uuid_only_and_does_not_register_on_get(
        self,
    ):
        saved = save_export(self.service.store, self.project.id, "csv", [b"x\n"])
        directory = saved.path.parent
        legacy = directory / ("f" * 32 + ".json")
        legacy.write_bytes(b"{}")
        (directory / "unrelated.json").write_bytes(b"unrelated")
        (directory / ("e" * 32 + ".json")).symlink_to(legacy)
        nested = directory / "nested"
        nested.mkdir()
        (nested / ("d" * 32 + ".csv")).write_bytes(b"not a direct export")
        with self.service.store.connect() as connection:
            before = connection.execute(
                "SELECT COUNT(*) FROM history_exports"
            ).fetchone()[0]
        self.assertEqual(self.history.list("export").total, 2)
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM history_exports").fetchone()[
                    0
                ],
                before,
            )
        with (
            patch("patent_sar_extractor.web.history_exports.MAX_SCAN_ENTRIES", 1),
            self.assertRaises(WebError) as error,
        ):
            self.history.list("export")
        self.assertEqual(error.exception.code, "history_export_limit")

    def test_metadata_does_not_initialize_analysis_or_environment_or_change_rows(self):
        before = {str(path.relative_to(self.state)) for path in self.state.rglob("*")}
        project = self.service.store.project(self.project.id)
        with self.service.store.connect() as connection:
            rows_before = "\n".join(connection.iterdump())
        started = time.perf_counter()
        for kind in ("project", "job", "export", "environment_operation"):
            self.history.list(kind)
        elapsed = time.perf_counter() - started
        with self.service.store.connect() as connection:
            self.assertEqual("\n".join(connection.iterdump()), rows_before)
        print(
            f"\nHistory metadata (four categories): {elapsed * 1000:.2f} ms; SQLite logical state unchanged."
        )
        self.assertEqual(self.service.store.project(self.project.id), project)
        self.assertEqual(
            {str(path.relative_to(self.state)) for path in self.state.rglob("*")},
            before,
        )
        self.assertFalse((self.state / "analysis").exists())
        self.assertFalse((self.state / "environments").exists())

    def test_delayed_projection_and_correction_cannot_publish_after_project_trash(self):
        from types import SimpleNamespace

        before = self.service.store.project(self.project.id)

        def trash_then_snapshot(*args, **kwargs):
            entry = self.history.get("project", self.project.id)
            self.history.delete("project", self.project.id, entry.revision)
            return {"is_historical": False, "acceptance": {"state": "accepted"}}, []

        self.service.refresh(
            self.project.id,
            view=SimpleNamespace(root=self.run, snapshot=trash_then_snapshot),
        )
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT snapshot FROM projects WHERE id=?", (self.project.id,)
                ).fetchone()[0],
                before["snapshot"],
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM compounds WHERE project_id=?",
                    (self.project.id,),
                ).fetchone()[0],
                1,
            )
        deleted = self.history.get("project", self.project.id)
        self.history.restore("project", self.project.id, deleted.revision)
        document = self.service.get_correction(self.project.id, "Compound 1")
        original_reader = self.service.corrections.current_project

        def trash_after_read(identifier):
            row = original_reader(identifier)
            entry = self.history.get("project", identifier)
            self.history.delete("project", identifier, entry.revision)
            return row

        request = CorrectionRequest(
            expected_revision=document.revision,
            expected_source_fingerprint=document.source_fingerprint,
            fields=document.values.model_copy(update={"display_id": "Not published"}),
        )
        with (
            patch.object(
                self.service.corrections,
                "current_project",
                side_effect=trash_after_read,
            ),
            self.assertRaises(WebError) as error,
        ):
            self.service.put_correction(self.project.id, "Compound 1", request)
        self.assertEqual(error.exception.status, 404)
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM correction_audit").fetchone()[
                    0
                ],
                0,
            )

    def test_delayed_enqueue_cannot_create_job_or_output_after_project_trash(self):
        from test_web_support import ExitRunner

        from patent_sar_extractor.web.jobs import JobQueue
        from patent_sar_extractor.web.models import JobRequest
        from patent_sar_extractor.web.workspace_locations import WorkspaceLocations

        queue = JobQueue(self.service, ExitRunner(), 30)
        original_root = WorkspaceLocations.result_root

        def trash_after_location(locations):
            root = original_root(locations)
            entry = self.history.get("project", self.project.id)
            self.history.delete("project", self.project.id, entry.revision)
            return root

        with (
            patch.object(WorkspaceLocations, "result_root", trash_after_location),
            self.assertRaises(WebError) as error,
        ):
            queue.enqueue(self.project.id, JobRequest(force=True))
        self.assertEqual(error.exception.status, 404)
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0
            )
        self.assertFalse((self.state / "runs" / self.project.id).exists())

    def test_shared_analysis_lease_blocks_project_delete_and_releases_after_errors(
        self,
    ):
        analysis = AnalysisService(
            self.state, self.service, settings=AnalysisSettings()
        )
        self.addCleanup(analysis.close)
        entry = self.history.get("project", self.project.id)
        with analysis._operation(None):
            busy = self.history.get("project", self.project.id)
            self.assertFalse(busy.can_delete)
            self.assertEqual(busy.revision, entry.revision)
            with self.assertRaises(WebError) as error:
                self.history.delete("project", self.project.id, entry.revision)
            self.assertEqual(error.exception.status, 409)
        with self.assertRaises(RuntimeError), analysis._operation(None):
            raise RuntimeError("controlled owned-operation failure")
        with self.assertRaises(WebError) as error:
            self.history.delete("project", self.project.id, "0" * 64)
        self.assertEqual(error.exception.code, "history_conflict")
        with analysis._operation(None):
            pass
        self.history.delete("project", self.project.id, entry.revision)

    def test_all_associated_jobs_guard_project_even_when_latest_is_terminal(self):
        row, _, _ = self.draft()
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "INSERT INTO jobs(id,project_id,status,created_at,spec) VALUES(?,?,'complete',?,'{}')",
                ("f" * 32, self.project.id, now()),
            )
        self.assertFalse(self.history.get("project", self.project.id).can_delete)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='interrupted',identity='retained' WHERE id=?",
                (row["id"],),
            )
        self.assertFalse(self.history.get("project", self.project.id).can_delete)

    def test_job_history_pagination_includes_more_than_the_public_500_limit(self):
        with self.service.store.connect(write=True) as connection:
            connection.executemany(
                "INSERT INTO jobs(id,project_id,status,created_at,spec) VALUES(?,?,'complete',?,'{}')",
                [(f"{index:032x}", self.project.id, now()) for index in range(1, 506)],
            )
        sixth = self.history.list("job", page=6, page_size=100)
        self.assertEqual(sixth.total, 505)
        self.assertEqual(len(sixth.items), 5)
        identifiers = {
            entry.id
            for page in range(1, 7)
            for entry in self.history.list("job", page=page, page_size=100).items
        }
        self.assertEqual(len(identifiers), 505)

    def test_trash_does_not_free_the_retained_two_hundred_project_limit(self):
        from patent_sar_extractor.web.pdf import copy_original

        with self.service.store.connect(write=True) as connection:
            connection.executemany(
                "INSERT INTO projects(id,title,patent_id,created_at,updated_at) VALUES(?,?,'',?,?)",
                [
                    (f"{index:032x}", "Retained test project", now(), now())
                    for index in range(1, 200)
                ],
            )
        entry = self.history.get("project", self.project.id)
        self.history.delete("project", entry.id, entry.revision)
        copied = copy_original(self.pdf, self.state / "uploads")
        with self.assertRaises(WebError) as error:
            self.service.add_pdf(copied, "controlled.pdf", None)
        self.assertEqual(error.exception.code, "project_limit")
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 200
            )

    def test_old_seeded_workspace_adds_tables_without_changing_data_or_audit(self):
        before = self.service.store.project(self.project.id)
        document = self.service.get_correction(self.project.id, "Compound 1")
        fields = document.values.model_copy(
            update={"display_id": "Reviewed source identifier"}
        )
        self.service.put_correction(
            self.project.id,
            "Compound 1",
            CorrectionRequest(
                expected_revision=document.revision,
                expected_source_fingerprint=document.source_fingerprint,
                fields=fields,
            ),
        )
        with self.service.store.connect(write=True) as connection:
            audit = [
                tuple(row)
                for row in connection.execute("SELECT * FROM correction_audit")
            ]
            connection.execute("DROP TABLE history_exports")
            connection.execute("DROP TABLE history_tombstones")
        reopened = Store(self.state)
        history = HistoryService(reopened)
        entry = history.get("project", self.project.id)
        deleted = history.delete("project", entry.id, entry.revision)
        history.restore("project", entry.id, deleted.revision)
        with reopened.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(), []
            )
            self.assertEqual(
                [
                    tuple(row)
                    for row in connection.execute("SELECT * FROM correction_audit")
                ],
                audit,
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM correction_audit")
        after = reopened.project(self.project.id)
        self.assertEqual(after["snapshot"], before["snapshot"])
        self.assertEqual(after["id"], before["id"])


class EnvironmentHistoryTests(PredictionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.environment = EnvironmentStore(self.state, self.root / "managed")
        self.history = HistoryService(self.service.store)

    def operation(self, request="controlled-request"):
        spec = {
            "schema_version": 1,
            "requires_owner_ack": True,
            "action": "inspect",
            "component_ids": ["base"],
            "install_root": str(self.root / "managed"),
            "bindings": {component: None for component in COMPONENT_IDS},
            "cache_root": str(self.state / "environments/downloads"),
            "config_fingerprint": "a" * 64,
            "source_key": "b" * 64,
        }
        operation, _ = self.environment.enqueue(request, "f" * 64, spec, 0)
        self.environment.update(
            operation.id,
            status="complete",
            finished_at=now(),
            log_tail=encode(["Retain forensic evidence"]),
        )
        return operation.id, spec

    def test_terminal_environment_history_delete_keeps_readiness_logs_and_idempotency(
        self,
    ):
        identifier, spec = self.operation()
        original = self.environment.row(identifier)
        settings = self.environment.settings()
        reports = self.environment.report_records()
        entry = self.history.get("environment_operation", identifier)
        deleted = self.history.delete(
            "environment_operation", identifier, entry.revision
        )
        self.assertEqual(self.environment.history(), [])
        with self.assertRaises(WebError):
            self.environment.public_row(identifier)
        with self.assertRaises(WebError):
            self.environment.request_cancel(identifier)
        self.assertEqual(self.environment.row(identifier), original)
        self.assertEqual(self.environment.settings(), settings)
        self.assertEqual(self.environment.report_records(), reports)
        with self.assertRaises(WebError) as error:
            self.environment.enqueue("controlled-request", "f" * 64, spec, 0)
        self.assertEqual(error.exception.code, "environment_operation_deleted")
        restored = HistoryService(self.service.store).restore(
            "environment_operation", identifier, deleted.revision
        )
        self.assertIsNone(restored.deleted_at)
        repeated, created = self.environment.enqueue(
            "controlled-request", "f" * 64, spec, 0
        )
        self.assertEqual(repeated.id, identifier)
        self.assertFalse(created)
        self.assertEqual(self.environment.row(identifier), original)

    def test_terminal_environment_retained_identity_cannot_be_hidden(self):
        identifier, _ = self.operation()
        self.environment.update(identifier, identity="unverified-producer")
        entry = self.history.get("environment_operation", identifier)
        self.assertFalse(entry.can_delete)
        self.assertIn("ownership", entry.blocked_reason)
        with self.assertRaises(WebError) as error:
            self.history.delete("environment_operation", identifier, entry.revision)
        self.assertEqual(error.exception.status, 409)

    def test_real_retained_environment_identity_live_blocks_then_absent_allows_without_rewrite(
        self,
    ):
        identifier, _ = self.operation()
        row = self.environment.row(identifier)
        spec, plan = environment_spec(row, self.state)
        output = private_directory(Path(spec.output_dir))
        private_directory(self.environment.root / "downloads")
        (output / "environment-plan.json").write_text(encode(plan))
        runner = EnvironmentProcessRunner()
        # The actual worker waits at its owner handshake. A deliberately wrong
        # acknowledgement then ends it before any SDK, inspection or download.
        identity = runner.start(spec)
        self.environment.update(identifier, identity=encode(identity.to_dict()))
        retained = self.environment.row(identifier)
        self.assertIsNotNone(environment_cleanup_block(retained, self.state))
        live = self.history.get("environment_operation", identifier)
        self.assertFalse(live.can_delete)
        (output / "environment-owner.json").write_text("{}")
        child = runner._children[identity.pid]
        child.wait(timeout=8)
        self.assertNotEqual(child.returncode, 0)
        runner._log_threads[identity.pid].join(timeout=2)
        # No runner.stop call: the validator only observes absence/reaped exit.
        self.assertIsNone(environment_cleanup_block(retained, self.state))
        removable = self.history.get("environment_operation", identifier)
        self.assertTrue(removable.can_delete)
        deleted = self.history.delete(
            "environment_operation", identifier, removable.revision
        )
        self.assertEqual(self.environment.row(identifier), retained)
        self.history.restore("environment_operation", identifier, deleted.revision)
        self.assertEqual(self.environment.row(identifier), retained)

    def retained_identity(self):
        from patent_sar_extractor.web.processes import ProcessIdentity

        identifier, _ = self.operation()
        spec, _ = environment_spec(self.environment.row(identifier), self.state)
        runner = EnvironmentProcessRunner()
        identity = ProcessIdentity(
            2**31 - 1,
            1,
            runner.boot_id,
            2**31 - 1,
            runner.command(spec),
            spec.output_dir,
            str(Path(runner.command(spec)[0]).resolve()),
        )
        self.environment.update(identifier, identity=encode(identity.to_dict()))
        return identifier, identity, runner

    def test_same_boot_leader_and_saved_descendants_must_all_be_absent(self):
        identifier, identity, _ = self.retained_identity()
        row = self.environment.row(identifier)
        self.assertIsNone(environment_cleanup_block(row, self.state))
        descendant = {
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "pgid": os.getpgrp(),
            "start_ticks": 1,
            "state": "S",
            "argv": ["/usr/bin/python3.12"],
            "cwd": str(self.state),
            "executable": "/usr/bin/python3.12",
        }
        identity.descendants.append(descendant)
        self.environment.update(identifier, identity=encode(identity.to_dict()))
        retained = self.environment.row(identifier)
        self.assertIsNotNone(environment_cleanup_block(retained, self.state))
        self.assertFalse(
            self.history.get("environment_operation", identifier).can_delete
        )
        self.assertEqual(self.environment.row(identifier), retained)

    def test_prior_valid_kernel_proves_absence_but_foreign_or_malformed_identity_stays_blocked(
        self,
    ):
        import uuid

        identifier, identity, _ = self.retained_identity()
        identity.boot_id = str(uuid.uuid4())
        identity.pid = identity.pgid = (
            os.getpid()
        )  # A reused current PID must not be signalled or inspected.
        original = encode(identity.to_dict())
        self.environment.update(identifier, identity=original)
        row = self.environment.row(identifier)
        with patch(
            "patent_sar_extractor.web.environment_cleanup.process_present",
            side_effect=AssertionError("current PID probe"),
        ):
            self.assertIsNone(environment_cleanup_block(row, self.state))
        variants = [
            "{malformed",
            encode({**identity.to_dict(), "boot_id": "unknown"}),
            encode({**identity.to_dict(), "cwd": "/foreign/workspace"}),
            encode(
                {
                    **identity.to_dict(),
                    "argv": ["/usr/bin/python3.12", "foreign-command"],
                }
            ),
            encode({**identity.to_dict(), "phase": "admet"}),
            encode({**identity.to_dict(), "executable": "/foreign/interpreter"}),
        ]
        for variant in variants:
            with self.subTest(variant=hashlib.sha256(variant.encode()).hexdigest()):
                self.environment.update(identifier, identity=variant)
                retained = self.environment.row(identifier)
                self.assertIsNotNone(environment_cleanup_block(retained, self.state))
                self.assertEqual(self.environment.row(identifier), retained)
        self.environment.update(identifier, identity=original)
        with patch(
            "patent_sar_extractor.web.environment_cleanup._current_boot",
            return_value="unknown",
        ):
            self.assertIsNotNone(
                environment_cleanup_block(self.environment.row(identifier), self.state)
            )

    def test_changed_saved_environment_plan_blocks_retained_identity_without_initialization(
        self,
    ):
        identifier, _, _ = self.retained_identity()
        row = self.environment.row(identifier)
        original = json.loads(row["spec"])
        variants = [
            {**original, "operation_id": "a" * 32},
            {**original, "action": "install"},
            {**original, "install_root": "/foreign/install"},
            {**original, "component_ids": ["unknown"]},
            {**original, "cache_root": "/foreign/cache"},
            {**original, "source_key": "unknown"},
            {**original, "bindings": "malformed"},
            {**original, "bindings": {"unknown": None}},
            {**original, "unexpected": "unsupported field"},
        ]
        before_paths = {
            str(path.relative_to(self.state)) for path in self.state.rglob("*")
        }
        for value in variants:
            with self.subTest(keys=sorted(value)):
                changed = {**row, "spec": encode(value)}
                self.assertIsNotNone(environment_cleanup_block(changed, self.state))
        self.assertEqual(
            {str(path.relative_to(self.state)) for path in self.state.rglob("*")},
            before_paths,
        )
        self.assertEqual(self.environment.row(identifier), row)

    def test_old_environment_metadata_does_not_initialize_locations_or_tombstones(self):
        identifier, _ = self.operation()
        with self.environment.connect(write=True) as connection:
            connection.execute("DROP TABLE history_tombstones")
            connection.execute("DROP TABLE file_roots")
            connection.execute("DROP TABLE file_settings")
        self.assertEqual(self.history.list("environment_operation").total, 1)
        entry = self.history.get("environment_operation", identifier)
        with self.environment.connect() as connection:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertNotIn("history_tombstones", names)
        self.assertNotIn("file_settings", names)
        self.history.delete("environment_operation", identifier, entry.revision)
        with self.environment.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertIsNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='file_settings'"
                ).fetchone()
            )

    def test_environment_history_pagination_includes_more_than_catalog_twenty(self):
        for index in range(25):
            self.operation(f"controlled-{index}")
        listing = self.history.list("environment_operation", page=3, page_size=10)
        self.assertEqual(listing.total, 25)
        self.assertEqual(len(listing.items), 5)
        self.assertEqual(len(self.environment.history()), 20)

    def test_trash_does_not_free_the_retained_thousand_operation_limit(self):
        identifier, spec = self.operation()
        entry = self.history.get("environment_operation", identifier)
        self.history.delete("environment_operation", identifier, entry.revision)
        with self.environment.connect(write=True) as connection:
            connection.executemany(
                "INSERT INTO operations(id,request_id,fingerprint,action,component_ids,install_root,status,created_at,spec) VALUES(?,?,?,'inspect','[]',?,'complete',?,'{}')",
                [
                    (
                        f"{index:032x}",
                        f"retained-{index}",
                        "a" * 64,
                        spec["install_root"],
                        now(),
                    )
                    for index in range(1, 1000)
                ],
            )
        with self.assertRaises(WebError) as error:
            self.environment.enqueue("new-request", "f" * 64, spec, 0)
        self.assertEqual(error.exception.code, "environment_history_limit")
        self.assertEqual(
            self.history.list("environment_operation", deleted=True).total, 1
        )


if __name__ == "__main__":
    unittest.main()
