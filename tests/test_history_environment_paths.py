"""Shared retained-plan parsing must preserve the queue's no-link boundary."""

from __future__ import annotations

import unittest

from test_web_support import WebFixture

from patent_sar_extractor.web.environment_records import environment_spec
from patent_sar_extractor.web.environment_storage import EnvironmentStore
from patent_sar_extractor.web.errors import WebError


class EnvironmentHistoryPathTests(WebFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.environment = EnvironmentStore(self.state, self.root / "install")
        operation, _ = self.environment.enqueue(
            "controlled-path-proof",
            "controlled-fingerprint",
            {
                "schema_version": 1,
                "action": "inspect",
                "component_ids": ["installer"],
                "install_root": str(self.root / "install"),
            },
            0,
        )
        self.row = self.environment.row(operation.id)
        self.operations = self.environment.root / "operations"
        self.output = self.operations / operation.id
        self.foreign = self.root / "foreign-private-directory"
        self.foreign.mkdir(mode=0o700)
        self.sentinel = self.foreign / "keep.txt"
        self.sentinel.write_text("Unrelated content must remain unchanged")

    def assert_blocked(self):
        with self.assertRaises(WebError) as caught:
            environment_spec(self.row, self.state)
        self.assertEqual(caught.exception.code, "environment_record")
        self.assertEqual(
            self.sentinel.read_text(), "Unrelated content must remain unchanged"
        )
        self.assertEqual(self.environment.row(self.row["id"]), self.row)

    def test_symlinked_attempt_cannot_enter_queue_or_terminal_cleanup_reader(self):
        self.operations.mkdir(mode=0o700)
        self.output.symlink_to(self.foreign, target_is_directory=True)
        self.assert_blocked()

    def test_symlinked_operations_ancestor_cannot_redirect_the_owned_plan(self):
        self.operations.symlink_to(self.foreign, target_is_directory=True)
        self.assert_blocked()

    def test_missing_owned_attempt_is_read_only_and_not_initialized(self):
        spec, _ = environment_spec(self.row, self.state)
        self.assertEqual(spec.output_dir, str(self.output))
        self.assertFalse(self.operations.exists())
