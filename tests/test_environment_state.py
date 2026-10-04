from __future__ import annotations

import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from patent_sar_extractor.web.environment_paths import ManagedStorage
from patent_sar_extractor.web.environment_storage import EnvironmentStore
from patent_sar_extractor.web.environments import EnvironmentManager
from patent_sar_extractor.web.errors import WebError


class EnvironmentStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.prefix = self.allowed / "managed"
        self.settings = ManagedStorage(self.allowed, self.prefix)
        self.store = EnvironmentStore(self.root / "state", self.prefix)

    def spec(self):
        return {
            "schema_version": 1,
            "action": "inspect",
            "component_ids": ["base"],
            "install_root": str(self.prefix),
        }

    def test_real_persistence_idempotency_and_conflicts(self):
        operation, created = self.store.enqueue(
            "request-1234567890", "same", self.spec(), 0
        )
        self.assertTrue(created)
        restarted = EnvironmentStore(self.root / "state", self.prefix)
        duplicate, created = restarted.enqueue(
            "request-1234567890", "same", self.spec(), 0
        )
        self.assertFalse(created)
        self.assertEqual(duplicate, operation)
        with self.assertRaisesRegex(WebError, "different operation"):
            self.store.enqueue("request-1234567890", "different", self.spec(), 0)
        with self.assertRaisesRegex(WebError, "active"):
            self.store.enqueue("request-abcdefghij", "next", self.spec(), 0)
        self.assertEqual(len(self.store.history()), 1)

    def test_settings_revision_and_active_operation_guard(self):
        updated = self.store.save_settings(self.prefix, 0)
        self.assertEqual(updated["revision"], 1)
        with self.assertRaisesRegex(WebError, "changed"):
            self.store.save_settings(self.prefix, 0)
        operation, _ = self.store.enqueue("request-1234567890", "same", self.spec(), 1)
        with self.assertRaisesRegex(WebError, "active"):
            self.store.save_settings(self.prefix, 1)
        self.store.request_cancel(operation.id)
        self.store.request_cancel(operation.id)
        self.assertEqual(self.store.row(operation.id)["cancel_requested"], 1)
        self.assertEqual(
            self.store.operation(self.store.row(operation.id)).status, "queued"
        )
        self.store.update(operation.id, status="cancelled")
        self.assertEqual(self.store.save_settings(self.prefix, 1)["revision"], 2)

    def test_concurrent_requests_never_create_competing_consumers(self):
        def enqueue(i):
            try:
                return self.store.enqueue(
                    f"parallel-request-{i}", str(i), self.spec(), 0
                )[0].id
            except WebError as error:
                self.assertEqual(error.code, "environment_busy")
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(enqueue, range(4)))
        self.assertEqual(sum(value is not None for value in results), 1)

    def test_reports_preserve_source_identity_for_current_or_historical_projection(self):
        self.store.publish_reports("identity-1", [{"id": "base", "status": "ready"}])
        saved = self.store.report_records()["base"]
        self.assertEqual(saved["report"]["status"], "ready")
        self.assertEqual(saved["source_key"], "identity-1")
        self.assertNotEqual(saved["source_key"], "identity-2")
        self.assertIsNotNone(self.store.settings()["checked_at"])

    def test_location_cannot_escape_or_replace_unknown_content(self):
        for value in (
            str(self.root),
            str(self.allowed),
            str(self.allowed / ".." / "escape"),
            "E:\\WSL\\apps\\x-patentsar",
            "/mnt/c/Users/Victor/test",
            "relative",
        ):
            with self.subTest(value=value), self.assertRaises(WebError):
                self.settings.validate(value)
        self.prefix.mkdir(mode=0o700)
        (self.prefix / "user.txt").write_text("preserve")
        with self.assertRaises(WebError):
            self.settings.prepare(str(self.prefix))
        self.assertEqual((self.prefix / "user.txt").read_text(), "preserve")

    def test_unknown_or_invalid_managed_marker_has_actionable_conflict(self):
        self.prefix.mkdir(mode=0o700)
        (self.prefix / "user.txt").write_text("preserve")
        for value in (None, "not json", '{"schema_version":999}'):
            marker = self.prefix / ".x-patentsar-environments.json"
            if value is not None:
                marker.write_text(value)
            with self.subTest(value=value), self.assertRaises(WebError) as context:
                self.settings.validate(str(self.prefix))
            self.assertEqual(context.exception.code, "environment_prefix_unknown")
            self.assertEqual((self.prefix / "user.txt").read_text(), "preserve")

    def test_public_existing_directory_is_not_saved_as_installable_or_chmodded(self):
        self.prefix.mkdir(mode=0o755)
        with self.assertRaisesRegex(WebError, "0700"):
            self.settings.validate(str(self.prefix))
        self.assertEqual(self.prefix.stat().st_mode & 0o777, 0o755)

    def test_dependency_closure_is_ordered_unique_and_rejects_unknown_or_cycles(self):
        manager = object.__new__(EnvironmentManager)
        cards = [
            {"id": "installer", "dependencies": []},
            {"id": "base", "dependencies": ["installer"]},
            {"id": "admet", "dependencies": ["installer"]},
            {"id": "admet-models", "dependencies": ["admet"]},
        ]
        manager.metadata = lambda: cards
        self.assertEqual(
            manager.resolve_components(["admet-models", "base", "installer"]),
            ["installer", "admet", "admet-models", "base"],
        )
        for dependencies in (["unknown"], ["base"]):
            cards[0]["dependencies"] = dependencies
            with self.subTest(dependencies=dependencies), self.assertRaises(WebError):
                manager.resolve_components(["base"])

    def test_owned_prefix_and_symlink_safety(self):
        self.assertEqual(self.settings.prepare(str(self.prefix)), self.prefix)
        self.assertEqual(self.settings.prepare(str(self.prefix)), self.prefix)
        link = self.allowed / "link"
        link.symlink_to(self.prefix, target_is_directory=True)
        with self.assertRaisesRegex(WebError, "symbolic"):
            self.settings.prepare(str(link / "new"))
        self.assertFalse((self.prefix / "new").exists())

    def test_database_symlinks_are_not_followed(self):
        target = self.root / "private"
        target.write_text("preserve")
        self.store.path.unlink()
        self.store.path.symlink_to(target)
        with self.assertRaisesRegex(WebError, "private regular"):
            EnvironmentStore(self.root / "state", self.prefix)
        self.assertEqual(target.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
