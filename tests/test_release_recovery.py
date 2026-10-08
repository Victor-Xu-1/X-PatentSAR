"""Ambiguous publication and mainline races cannot repeat a release increment."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.release_publication_support import GitPublicationFixture
from tools import prepare_pr_version as automation


class ReleasePublicationRecoveryTests(GitPublicationFixture, unittest.TestCase):
    def test_unknown_ref_update_is_confirmed_without_a_duplicate_write(self):
        def uncertain(method, path, value=None):
            response = self.answer(method, path, value)
            if method == "PATCH":
                raise ValueError("Controlled response loss after accepted update")
            if path == "/git/ref/heads/feat/version":
                return {"object": {"sha": "d" * 40}}
            return response

        with patch.object(self.api, "call", side_effect=uncertain):
            automation.publish(self.api, self.root, self.record)
        self.assertEqual(sum(method == "PATCH" for method, _, _ in self.calls), 1)
        self.assertEqual(sum(path == "/git/commits" for _, path, _ in self.calls), 1)
        self.assertEqual(
            sum(path.endswith("/dispatches") for _, path, _ in self.calls), 1
        )

    def test_main_advancing_before_publication_preserves_branch_and_withholds_ci(self):
        seen = 0

        def racing(method, path, value=None):
            nonlocal seen
            response = self.answer(method, path, value)
            if path == "/git/ref/heads/main":
                seen += 1
                if seen > 1:
                    return {"object": {"sha": "e" * 40}}
            return response

        with (
            patch.object(self.api, "call", side_effect=racing),
            self.assertRaises(ValueError),
        ):
            automation.publish(self.api, self.root, self.record)
        self.assertFalse(
            any(
                method == "PATCH" or path.endswith("/dispatches")
                for method, path, _ in self.calls
            )
        )

    def test_a_known_failed_ci_run_never_creates_a_retry_loop(self):
        head = "e" * 40
        with patch.object(
            self.api,
            "call",
            return_value={
                "workflow_runs": [{"head_sha": head, "conclusion": "failure"}]
            },
        ) as call:
            automation.ensure_ci(self.api, head, "feat/version", self.base)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[0], "GET")


if __name__ == "__main__":
    unittest.main()
