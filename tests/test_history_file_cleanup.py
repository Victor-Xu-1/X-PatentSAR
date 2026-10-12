"""Real private files/SQLite/kernel leases; no production data or model task."""

import hashlib
import os
import sqlite3
import unittest
import uuid
from unittest.mock import patch

from test_prediction_support import PredictionFixture

from patent_sar_extractor.web.environment_storage import EnvironmentStore
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.history_asset_removal import remove_empty_directory
from patent_sar_extractor.web.history_purge_models import TrashClearRequest
from patent_sar_extractor.web.history_service import HistoryService
from patent_sar_extractor.web.pdf import UploadedPDF
from patent_sar_extractor.web.sar.models import ProjectSnapshot
from patent_sar_extractor.web.sar.service import SARService
from patent_sar_extractor.web.storage import now


class HistoryFileCleanupTests(PredictionFixture, unittest.TestCase):
    def test_shared_environment_in_operator_selected_output_location_is_never_deleted(
        self,
    ):
        shared = self.output / "shared-runtime"
        shared.mkdir()
        binary = shared / "keep-sdk.bin"
        binary.write_bytes(
            b"Shared installed runtime must not be treated as an artifact"
        )
        environment = EnvironmentStore(self.state, shared)
        settings = environment.settings()
        self.remove_project()
        request, plan = self.request()
        self.assertEqual(plan.files_total, 1)
        receipt = self.history.clear_trash(request)
        self.assertEqual(receipt.status, "complete")
        self.assertTrue(binary.exists())
        self.assertTrue(self.generated.exists())
        self.assertEqual(environment.settings(), settings)

    def test_empty_directory_phase_is_bounded_and_resumes_after_files_are_processed(
        self,
    ):
        self.remove_project()
        request, _ = self.request()
        clock = {"value": 0}

        def finish_one(*args):
            remove_empty_directory(*args)
            clock["value"] = 31

        with (
            patch(
                "patent_sar_extractor.web.history_asset_cleanup.time.monotonic",
                side_effect=lambda: clock["value"],
            ),
            patch(
                "patent_sar_extractor.web.history_asset_cleanup.remove_empty_directory",
                side_effect=finish_one,
            ),
        ):
            pending = self.history.clear_trash(request)
        self.assertEqual(pending.status, "cleanup_pending")
        self.assertEqual(pending.files_deleted, 3)
        with self.service.store.connect() as connection:
            progress = connection.execute(
                "SELECT next_directory FROM history_file_cleanup WHERE request_id=?",
                (request.request_id,),
            ).fetchone()[0]
        self.assertEqual(progress, 1)
        complete = HistoryService(self.service.store).clear_trash(request)
        self.assertEqual(complete.status, "complete")
        self.assertEqual(complete.files_deleted, 3)
        self.assertFalse(self.output.exists())

    def setUp(self):
        super().setUp()
        self.history = HistoryService(self.service.store)
        self.original = self.service.store.locations.pdf_path(
            self.service.store.project(self.project.id)
        )
        row, self.output, _ = self.draft()
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='failed',finished_at=? WHERE id=?",
                (now(), row["id"]),
            )
        self.job = row["id"]
        self.generated = self.output / "structure.json"
        self.generated.write_bytes(
            b"Controlled extraction asset, not chemistry evidence"
        )
        self.nested = self.output / "crops"
        self.nested.mkdir()
        self.crop = self.nested / "source.png"
        self.crop.write_bytes(b"Controlled retained/candidate image bytes")
        self.unrelated = self.root / "do-not-delete.txt"
        self.unrelated.write_bytes(b"Unrelated input, environment and archives remain")

    def remove_project(self):
        entry = self.history.get("project", self.project.id)
        self.history.delete(entry.kind, entry.id, entry.revision)

    def request(self):
        plan = self.history.trash_plan()
        return TrashClearRequest(
            request_id=uuid.uuid4().hex,
            expected_revision=plan.revision,
            expected_total=plan.total,
        ), plan

    def assert_protected(self):
        self.assertTrue(self.pdf.exists())
        self.assertTrue(self.run.exists())
        self.assertEqual(
            self.unrelated.read_bytes(),
            b"Unrelated input, environment and archives remain",
        )

    def test_cleans_owned_unreferenced_original_and_nested_products_not_imported_directory(
        self,
    ):
        self.remove_project()
        request, plan = self.request()
        self.assertEqual(plan.files_total, 3)
        receipt = self.history.clear_trash(request)
        self.assertEqual(receipt.status, "complete")
        self.assertEqual(receipt.files_deleted, 3)
        self.assertEqual(receipt.bytes_removed, plan.bytes_total)
        self.assertFalse(self.original.exists())
        self.assertFalse(self.output.exists())
        self.assert_protected()
        self.assertEqual(self.history.clear_trash(request), receipt)

    def test_visible_project_keeps_original_and_current_or_historical_attempts(self):
        entry = self.history.get("job", self.job)
        self.history.delete(entry.kind, entry.id, entry.revision)
        request, plan = self.request()
        self.assertEqual(plan.files_total, 0)
        receipt = self.history.clear_trash(request)
        self.assertEqual(receipt.status, "complete")
        self.assertTrue(self.original.exists())
        self.assertTrue(self.generated.exists())
        self.assertTrue(self.crop.exists())

    def test_shared_original_is_retained_for_another_visible_project(self):
        digest = hashlib.sha256(self.original.read_bytes()).hexdigest()
        other = self.service.add_pdf(
            UploadedPDF(self.original, digest, 1), "shared.pdf", "Visible shared source"
        )
        self.remove_project()
        request, plan = self.request()
        self.assertEqual(plan.files_total, 2)
        receipt = self.history.clear_trash(request)
        self.assertEqual(receipt.files_deleted, 2)
        self.assertEqual(self.service.store.project(other.id)["sha256"], digest)
        self.assertTrue(self.original.exists())
        self.assertFalse(self.output.exists())

    def test_sar_snapshot_retains_complete_original_structure_and_attempt_evidence(
        self,
    ):
        sar = SARService(self.service)
        dataset = sar.from_project(
            ProjectSnapshot(project_id=self.project.id, request_id=uuid.uuid4().hex)
        )
        self.remove_project()
        request, plan = self.request()
        self.assertEqual(plan.files_total, 0)
        receipt = self.history.clear_trash(request)
        self.assertEqual(receipt.files_deleted, 0)
        self.assertTrue(self.original.exists())
        self.assertTrue(self.crop.exists())
        self.assertEqual(
            sar.datasets.get(dataset.id).source_project_id, self.project.id
        )

    def test_changed_content_or_inventory_requires_fresh_confirmation_before_any_write(
        self,
    ):
        self.remove_project()
        request, _ = self.request()
        self.generated.write_bytes(b"Changed after the frozen confirmation")
        with self.assertRaises(WebError) as error:
            self.history.clear_trash(request)
        self.assertEqual(error.exception.code, "history_clear_conflict")
        self.assertTrue(self.original.exists())
        self.assertTrue(self.crop.exists())
        self.assertEqual(self.history.trash_plan().total, request.expected_total)

    def test_open_file_kernel_lease_keeps_busy_products_without_privileged_proc_access(
        self,
    ):
        self.remove_project()
        with self.generated.open("rb"):
            request, plan = self.request()
            self.assertEqual(plan.files_total, 1)
            receipt = self.history.clear_trash(request)
        self.assertEqual(receipt.files_deleted, 1)
        self.assertTrue(self.generated.exists())
        self.assertTrue(self.crop.exists())
        self.assertFalse(self.original.exists())

    def test_hardlink_symlink_and_special_file_targets_are_not_followed_or_partially_adopted(
        self,
    ):
        self.remove_project()
        linked = self.output / "foreign-link"
        linked.symlink_to(self.unrelated)
        request, plan = self.request()
        self.assertEqual(plan.files_total, 1)
        receipt = self.history.clear_trash(request)
        self.assertEqual(receipt.status, "complete")
        self.assertTrue(linked.is_symlink())
        self.assertTrue(self.generated.exists())
        self.assert_protected()

    def test_hardlinked_generated_file_preserves_both_links(self):
        shared = self.root / "shared-linked-file"
        os.link(self.generated, shared)
        self.remove_project()
        request, plan = self.request()
        self.assertEqual(plan.files_total, 1)
        self.history.clear_trash(request)
        self.assertTrue(shared.exists())
        self.assertTrue(self.generated.exists())

    def test_database_failure_publishes_no_intent_and_deletes_no_file(self):
        self.remove_project()
        request, _ = self.request()
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "CREATE TRIGGER fail_cleanup BEFORE INSERT ON history_file_cleanup BEGIN SELECT RAISE(ABORT,'controlled rollback'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.history.clear_trash(request)
        self.assertTrue(self.original.exists())
        self.assertTrue(self.generated.exists())
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM history_purged_entries"
                ).fetchone()[0],
                0,
            )

    def test_quarantine_failure_is_explicit_and_exact_saved_request_resumes_after_restart(
        self,
    ):
        self.remove_project()
        request, _ = self.request()
        with patch(
            "patent_sar_extractor.web.history_asset_removal.os.unlink",
            side_effect=OSError("controlled interruption"),
        ):
            pending = self.history.clear_trash(request)
        self.assertEqual(pending.status, "cleanup_pending")
        self.assertEqual(pending.files_deleted, 0)
        restarted = HistoryService(self.service.store)
        self.assertEqual(restarted.trash_plan().pending, pending)
        self.assertEqual(restarted.clear_receipt(request.request_id), pending)
        stages = list(self.state.rglob(".patentsar-clear-*"))
        self.assertEqual(len(stages), 1)
        complete = restarted.clear_trash(request)
        self.assertEqual(complete.status, "complete")
        self.assertEqual(complete.files_deleted, 3)
        self.assertFalse(list(self.state.rglob(".patentsar-clear-*")))
        self.assertFalse(self.output.exists())
        self.assert_protected()

    def test_publication_crash_after_unlink_resumes_missing_authorized_files_without_recounting(
        self,
    ):
        self.remove_project()
        request, _ = self.request()
        with (
            patch(
                "patent_sar_extractor.web.history_asset_cleanup._progress",
                side_effect=sqlite3.OperationalError("controlled checkpoint failure"),
            ),
            self.assertRaises(sqlite3.OperationalError),
        ):
            self.history.clear_trash(request)
        self.assertEqual(
            self.history.clear_receipt(request.request_id).status, "cleanup_pending"
        )
        complete = HistoryService(self.service.store).clear_trash(request)
        self.assertEqual(complete.status, "complete")
        self.assertEqual(complete.files_deleted, 3)
        self.assertFalse(self.original.exists())
        self.assert_protected()

    def test_new_shared_reference_during_pending_cleanup_is_retained_not_deleted_on_resume(
        self,
    ):
        self.remove_project()
        request, _ = self.request()
        with patch(
            "patent_sar_extractor.web.history_asset_cleanup.remove_file",
            side_effect=OSError("controlled interruption"),
        ):
            pending = self.history.clear_trash(request)
        self.assertEqual(pending.status, "cleanup_pending")
        digest = hashlib.sha256(self.original.read_bytes()).hexdigest()
        self.service.add_pdf(
            UploadedPDF(self.original, digest, 1), "shared.pdf", "New retained source"
        )
        complete = self.history.clear_trash(request)
        self.assertEqual(complete.status, "complete")
        self.assertEqual(complete.files_retained, 1)
        self.assertEqual(complete.files_deleted, 2)
        self.assertTrue(self.original.exists())

    def test_changed_or_unsealed_manifest_refuses_cleanup_without_deleting_remaining_data(
        self,
    ):
        self.remove_project()
        request, _ = self.request()
        with patch(
            "patent_sar_extractor.web.history_asset_cleanup.remove_file",
            side_effect=OSError("controlled interruption"),
        ):
            self.history.clear_trash(request)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE history_file_cleanup SET sha256=? WHERE request_id=?",
                ("0" * 64, request.request_id),
            )
        with self.assertRaises(WebError) as error:
            self.history.clear_trash(request)
        self.assertEqual(error.exception.code, "history_cleanup_manifest")
        self.assertTrue(self.original.exists())
        self.assertTrue(self.generated.exists())


if __name__ == "__main__":
    unittest.main()
