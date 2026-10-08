"""Local validation/cache recovery oracles; no DNS, provider or paid API call."""

from __future__ import annotations

import errno
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from patent_sar_extractor.integrations.llm import client, response_cache

VALID = '{"candidate_id":"allowed"}'
INVALID = '{"candidate_id":"invented"}'
MESSAGES = [{"role": "user", "content": "Select a supplied candidate only."}]


def envelope(content: str) -> bytes:
    return json.dumps(
        {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    ).encode()


class ClientRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.cache_path = str(Path(temporary) / "private" / "responses.sqlite")
        self.config = {
            "endpoint": "https://api.example.org/v1",
            "api_key": "controlled-cache-test-key",
            "model": "controlled",
            "cache_path": self.cache_path,
        }
        self.problems = []
        self.carrier = self.enterContext(
            patch.object(client, "bounded_post", return_value=envelope(VALID))
        )
        self.enterContext(
            patch.object(
                requests.sessions.Session, "request", side_effect=AssertionError
            )
        )

    def validate(self, content):
        if json.loads(content) != {"candidate_id": "allowed"}:
            raise ValueError("private rejected content must never reach logs")

    def call(self, **kwargs):
        options = {
            "config": self.config,
            "validate_content": self.validate,
            "validation_identity": "supplied-selection-v1",
            "on_failure": self.problems.append,
        }
        options.update(kwargs)
        return client.llm_chat(MESSAGES, **options)

    def key(self, validation_identity="supplied-selection-v1"):
        return response_cache._cache_key(
            MESSAGES,
            "controlled",
            0.0,
            self.config["endpoint"],
            max_response_chars=8192,
            validation_identity=validation_identity,
        )

    def seed(self, content, *, key=None):
        response_cache._cache_set(
            key or self.key(), content, cache_path=self.cache_path
        )

    def cached(self, key=None):
        return response_cache._cached(key or self.key(), cache_path=self.cache_path)

    def test_invalid_fresh_content_is_never_cached_or_retried(self):
        self.carrier.return_value = envelope(INVALID)
        with self.assertLogs(client.logger, level="WARNING") as logs:
            self.assertEqual(self.call(max_retries=1), "")
        self.assertIsNone(self.cached())
        self.assertEqual(self.carrier.call_count, 1)
        self.assertEqual(self.problems[-1].reason, "invalid_content")
        self.assertNotIn("private rejected content", " ".join(logs.output))

    def test_invalid_cached_entry_is_evicted_before_one_budgeted_request(self):
        self.seed(INVALID)
        self.seed("unrelated", key="other-key")

        def reserve():
            self.assertIsNone(self.cached())
            self.assertEqual(self.cached("other-key"), "unrelated")
            return True

        budget = Mock(side_effect=reserve)
        self.assertEqual(self.call(before_request=budget), VALID)
        self.assertEqual(self.cached(), VALID)
        self.assertEqual(self.carrier.call_count, 1)
        budget.assert_called_once_with()
        self.assertEqual(self.problems[0].reason, "invalid_cached_content")

    def test_invalid_cached_entry_cannot_bypass_exhausted_budget(self):
        self.seed(INVALID)
        self.seed("unrelated", key="other-key")
        self.assertEqual(self.call(before_request=lambda: False, max_retries=1), "")
        self.assertIsNone(self.cached())
        self.assertEqual(self.cached("other-key"), "unrelated")
        self.carrier.assert_not_called()
        self.assertEqual(
            [item.reason for item in self.problems],
            ["invalid_cached_content", "budget_exhausted"],
        )

    def test_eviction_does_not_delete_concurrently_replaced_content(self):
        self.seed(INVALID)
        self.seed(VALID)
        response_cache._cache_discard(self.key(), INVALID, cache_path=self.cache_path)
        self.assertEqual(self.cached(), VALID)

    def test_validation_identity_invalidates_only_legacy_namespace(self):
        self.seed(INVALID, key=self.key(""))
        self.assertEqual(self.call(), VALID)
        self.assertEqual(self.cached(self.key("")), INVALID)
        self.assertEqual(self.cached(), VALID)
        self.assertEqual(self.carrier.call_count, 1)

    def test_valid_cache_hit_is_revalidated_without_budget_or_request(self):
        self.seed(VALID)
        validator = Mock(side_effect=self.validate)
        budget = Mock(return_value=True)
        self.assertEqual(
            self.call(validate_content=validator, before_request=budget), VALID
        )
        validator.assert_called_once_with(VALID)
        self.carrier.assert_not_called()
        budget.assert_not_called()

    def test_real_sqlite_lock_does_not_discard_a_valid_response(self):
        self.seed("unrelated", key="other-key")
        with sqlite3.connect(self.cache_path) as locked:
            locked.execute("BEGIN EXCLUSIVE")
            started = time.monotonic()
            self.assertEqual(self.call(timeout=1), VALID)
            self.assertLess(time.monotonic() - started, 0.8)
        self.assertEqual(self.carrier.call_count, 1)
        self.assertTrue(self.problems)
        self.assertTrue(
            all(item.reason == "cache_unavailable" for item in self.problems)
        )

    def test_safe_cache_io_failures_preserve_validated_fresh_content(self):
        for failure in (
            OSError(errno.EIO, "private-cache-path"),
            sqlite3.OperationalError("disk I/O error"),
        ):
            with (
                self.subTest(failure=type(failure).__name__),
                patch.object(response_cache, "_get_cache_db", side_effect=failure),
            ):
                self.assertEqual(self.call(), VALID)
        self.assertEqual(self.carrier.call_count, 2)
        self.assertTrue(
            all(item.reason == "cache_unavailable" for item in self.problems)
        )

    def test_cache_write_failure_after_validation_is_not_an_api_retry(self):
        validator = Mock(side_effect=self.validate)

        def unavailable(*args, **kwargs):
            validator.assert_called_once_with(VALID)
            raise sqlite3.OperationalError("database is locked")

        with patch.object(client, "_cache_set", side_effect=unavailable):
            self.assertEqual(
                self.call(validate_content=validator, max_retries=1), VALID
            )
        self.assertEqual(self.carrier.call_count, 1)
        self.assertEqual(self.problems[-1].reason, "cache_unavailable")

    def test_unsafe_cache_directory_and_file_permissions_fail_closed(self):
        directory = Path(self.cache_path).parent
        directory.mkdir(mode=0o700)
        for target in (directory, Path(self.cache_path)):
            with self.subTest(target=target.name):
                if target != directory:
                    self.seed(VALID)
                target.chmod(0o755 if target == directory else 0o644)
                try:
                    with self.assertRaises(ValueError):
                        self.call()
                finally:
                    target.chmod(0o700 if target == directory else 0o600)
        self.carrier.assert_not_called()
        self.assertEqual(self.problems, [])

    def test_permission_errors_and_corrupt_sqlite_are_not_optional_cache_io(self):
        for failure in (
            PermissionError(errno.EACCES, "private-path"),
            sqlite3.DatabaseError("file is not a database"),
        ):
            with (
                self.subTest(failure=type(failure).__name__),
                patch.object(response_cache, "_get_cache_db", side_effect=failure),
                self.assertRaises(type(failure)),
            ):
                self.call()
        self.carrier.assert_not_called()
        self.assertEqual(self.problems, [])

    def test_symlink_cache_is_rejected_without_touching_target(self):
        directory = Path(self.cache_path).parent
        directory.mkdir(mode=0o700)
        target = directory / "retained.sqlite"
        self.seed("retained", key="other-key")
        Path(self.cache_path).rename(target)
        Path(self.cache_path).symlink_to(target)
        with self.assertRaises(ValueError):
            self.call()
        self.carrier.assert_not_called()
        self.assertEqual(
            response_cache._cached("other-key", cache_path=str(target)), "retained"
        )

    def test_cancellation_during_validation_prevents_cache_and_return(self):
        cancel = threading.Event()

        def validate(content):
            self.validate(content)
            cancel.set()

        self.assertEqual(self.call(validate_content=validate, cancel=cancel), "")
        self.assertIsNone(self.cached())
        self.assertEqual(self.problems[-1].reason, "cancelled")

    def test_deadline_and_cancel_are_rechecked_after_budget_reservation(self):
        for mode in ("deadline", "cancel"):
            cancel = threading.Event()
            clock = [100.0]

            def reserve(mode=mode, clock=clock, cancel=cancel):
                if mode == "deadline":
                    clock[0] = 102.0
                else:
                    cancel.set()
                return True

            with (
                self.subTest(mode=mode),
                patch.object(
                    client.time, "monotonic", side_effect=lambda clock=clock: clock[0]
                ),
            ):
                self.assertEqual(
                    self.call(
                        cache=False, timeout=1, before_request=reserve, cancel=cancel
                    ),
                    "",
                )
        self.carrier.assert_not_called()

    def test_timeout_reason_is_safe_and_default_does_not_retry(self):
        self.carrier.side_effect = requests.Timeout("private request and key")
        self.assertEqual(self.call(cache=False), "")
        self.assertEqual(self.carrier.call_count, 1)
        self.assertEqual(self.problems[-1].reason, "timeout")
        self.assertIsNone(self.problems[-1].http_status)
        self.assertNotIn("private request", repr(self.problems[-1]))

    def test_opt_in_timeout_retry_has_one_deadline_and_two_reservations(self):
        self.carrier.side_effect = [
            requests.Timeout("private request"),
            envelope(VALID),
        ]
        budget = Mock(return_value=True)
        self.assertEqual(
            self.call(cache=False, max_retries=1, before_request=budget), VALID
        )
        self.assertEqual((self.carrier.call_count, budget.call_count), (2, 2))
        first, second = self.carrier.call_args_list
        self.assertEqual(first.kwargs["deadline"], second.kwargs["deadline"])
        self.assertLess(second.kwargs["timeout"], first.kwargs["timeout"])

    def test_nonrecoverable_hook_failures_remain_explicit(self):
        self.carrier.side_effect = requests.Timeout()

        def failed_persistence(problem):
            raise PermissionError("controlled private fault-state refusal")

        with self.assertRaises(PermissionError):
            self.call(cache=False, on_failure=failed_persistence)
        self.assertEqual(self.carrier.call_count, 1)


class APIProblemTests(unittest.TestCase):
    def test_problem_is_immutable_and_json_serializable(self):
        from patent_sar_extractor.integrations.llm.api_failures import APIProblem

        problem = APIProblem("rate_limited", 429, True, 1.5)
        self.assertEqual(
            APIProblem.from_dict(json.loads(json.dumps(problem.to_dict()))), problem
        )
        with self.assertRaises(FrozenInstanceError):
            problem.reason = "timeout"

    def test_problem_rejects_unbounded_or_sensitive_metadata(self):
        from patent_sar_extractor.integrations.llm.api_failures import APIProblem

        for values in (
            {"reason": "raw-private-provider-body"},
            {"reason": "timeout", "http_status": True},
            {"reason": "timeout", "http_status": 1000},
            {"reason": "timeout", "retryable": "yes"},
            {"reason": "timeout", "retry_after_seconds": float("nan")},
            {"reason": "timeout", "retry_after_seconds": -1.0},
            {"reason": "timeout", "retry_after_seconds": 100000.0},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                APIProblem(**values)


if __name__ == "__main__":
    unittest.main()
