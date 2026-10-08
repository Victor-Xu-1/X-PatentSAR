"""Bounded PR metadata workflow regression; no actual GitHub writes or secrets."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tests.release_publication_support import GitPublicationFixture, IncomingPullFixture
from tests.test_release_policy import authority, fixture
from tools import prepare_pr_version as automation
from tools.release_github import GitHub, NoRedirects
from tools.release_scope import SCOPE, VERSION_TESTS, prepare_scope
from tools.version_policy import VERSION_PATHS, prepare_versions


class ReleaseScopeTests(unittest.TestCase):
    def plan(self):
        return {
            "schema_version": 1,
            "base_sha": "a" * 40,
            "changed_paths": ["frontend/tests/feature.test.ts"],
            "python_modules": ["tests.test_feature"],
            "frontend_tests": ["frontend/tests/feature.test.ts"],
            "browser_tests": ["frontend/e2e/feature.spec.ts"],
        }

    def test_scope_adds_only_direct_version_consumers_and_preserves_author_tests(self):
        original = self.plan()
        result = json.loads(
            prepare_scope(json.dumps(original), "a" * 40, ["README.md", *VERSION_PATHS])
        )
        self.assertEqual(
            result["python_modules"], ["tests.test_feature", *VERSION_TESTS]
        )
        for field in ("frontend_tests", "browser_tests", "base_sha", "schema_version"):
            self.assertEqual(result[field], original[field])
        self.assertEqual(
            result["changed_paths"], sorted(["README.md", SCOPE, *VERSION_PATHS])
        )
        self.assertEqual(
            json.loads(
                prepare_scope(json.dumps(result), "a" * 40, result["changed_paths"])
            ),
            result,
        )

    def test_parent_selection_is_not_duplicated(self):
        plan = self.plan()
        plan["python_modules"] = ["tests.test_release_policy", "tests.test_standalone"]
        self.assertEqual(
            json.loads(prepare_scope(json.dumps(plan), "a" * 40, []))["python_modules"],
            plan["python_modules"],
        )

    def test_stale_or_oversize_or_invalid_scope_stays_blocked(self):
        for replacement in (
            {"base_sha": "b" * 40},
            {"schema_version": True},
            {"python_modules": ["tests.test_" + str(i) for i in range(32)]},
            {"browser_tests": "global"},
            {"extra": 1},
        ):
            with self.subTest(value=replacement), self.assertRaises(ValueError):
                prepare_scope(json.dumps({**self.plan(), **replacement}), "a" * 40, [])


class IncomingPullTests(IncomingPullFixture, unittest.TestCase):
    def test_fork_closed_foreign_and_stale_pr_cannot_be_written(self):
        api = GitHub("owner/repo", "controlled-test-token")
        self.assertEqual(
            automation.validate_pull(api, self.pull(), "a" * 40),
            (45, "b" * 40, "feat/version"),
        )
        closed = self.pull()
        closed["state"] = "closed"
        self.assertIsNone(automation.validate_pull(api, closed, "a" * 40))
        for key, field, value in (
            ("head", "ref", "main"),
            ("head", "ref", "feat/$(bad)"),
            ("head", "sha", "bad"),
            ("base", "sha", "c" * 40),
            ("base", "ref", "other"),
        ):
            pull = self.pull()
            pull[key][field] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                automation.validate_pull(api, pull, "a" * 40)
        pull = self.pull()
        pull["head"]["repo"]["full_name"] = "untrusted/fork"
        with self.assertRaises(ValueError):
            automation.validate_pull(api, pull, "a" * 40)

    def test_workflow_run_ignores_main_push_and_foreign_artifacts(self):
        api = GitHub("owner/repo", "controlled-test-token")
        with patch.object(
            api, "call", side_effect=AssertionError("No request permitted")
        ):
            for run in (
                {"event": "push"},
                {
                    "event": "pull_request",
                    "head_repository": {"full_name": "attacker/fork"},
                },
            ):
                self.assertIsNone(automation.open_pull(api, {"workflow_run": run}))

    def test_transport_refuses_redirects_foreign_paths_and_credentials_in_errors(self):
        for name in ("bad/repo/extra", "https://evil.test"):
            with self.assertRaises(ValueError):
                GitHub(name, "secret")
        api = GitHub("owner/repo", "secret")
        for path in ("https://evil.test", "/../outside", "/path#fragment"):
            with self.assertRaises(ValueError):
                api.call("GET", path)
        with self.assertRaises(ValueError):
            NoRedirects().redirect_request(
                None, None, 302, None, None, "https://evil.test"
            )


class PublishTests(GitPublicationFixture, unittest.TestCase):
    def test_data_only_update_is_fast_forward_exactly_four_files_and_dispatches_ci(
        self,
    ):
        with patch.object(self.api, "call", side_effect=self.answer):
            automation.publish(self.api, self.root, self.record)
        tree = next(value for method, path, value in self.calls if path == "/git/trees")
        self.assertEqual(
            {item["path"] for item in tree["tree"]}, {*VERSION_PATHS, SCOPE}
        )
        update = next(value for method, path, value in self.calls if method == "PATCH")
        self.assertEqual(update, {"sha": "d" * 40, "force": False})
        self.assertEqual(
            self.calls[-1],
            (
                "POST",
                "/actions/workflows/ci.yml/dispatches",
                {"ref": "feat/version", "inputs": {"base_sha": self.base}},
            ),
        )
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.base)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_repeat_or_already_prepared_pr_has_no_api_writes(self):
        self.git("checkout", self.head)
        self.write(prepare_versions(authority(), fixture()))
        self.git("add", ".")
        self.git("commit", "-m", "prepared")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.record["head"]["sha"] = self.head
        self.git("update-ref", "refs/pull/45/head", self.head)
        self.git("checkout", self.base)
        with patch.object(self.api, "call", side_effect=self.answer):
            automation.publish(self.api, self.root, self.record)
        self.assertTrue(all(method == "GET" for method, _, _ in self.calls))

    def test_racing_head_cannot_publish_or_dispatch(self):
        def racing(method, path, value=None):
            response = self.answer(method, path, value)
            if path == "/pulls/45":
                response["head"]["sha"] = "e" * 40
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

    def test_missing_ci_dispatch_is_recovered_without_another_version_commit(self):
        self.git("checkout", self.head)
        self.write(prepare_versions(authority(), fixture()))
        self.git("add", ".")
        self.git("commit", "-m", "prepared without dispatch")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.record["head"]["sha"] = self.head
        self.git("update-ref", "refs/pull/45/head", self.head)
        self.git("checkout", self.base)

        def missing(method, path, value=None):
            response = self.answer(method, path, value)
            return (
                {"workflow_runs": []}
                if path.startswith("/actions/workflows/ci.yml/runs?")
                else response
            )

        with patch.object(self.api, "call", side_effect=missing):
            automation.publish(self.api, self.root, self.record)
        writes = [(method, path) for method, path, _ in self.calls if method != "GET"]
        self.assertEqual(writes, [("POST", "/actions/workflows/ci.yml/dispatches")])


if __name__ == "__main__":
    unittest.main()
