"""Failure causes, tail redaction and true streamed/cached byte progress."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_environment_recipes import RecipeFixture

from patent_sar_extractor.workers.environment_assets import download
from patent_sar_extractor.workers.environment_commands import (
    install_environment,
    run_command,
)
from patent_sar_extractor.workers.environment_errors import (
    DiagnosticTail,
    EnvironmentFailure,
    failure_from_exception,
)
from patent_sar_extractor.workers.environment_recipes import segmentation_config


class DiagnosticTests(RecipeFixture):
    def test_real_nonzero_child_preserves_safe_cause_not_credentials_paths_or_query(
        self,
    ):
        script = (
            "import sys; print('error: Failed to download https://files.pythonhosted.org/file?q=private-value'); "
            "print('Caused by: connection refused /private/operator/location'); "
            "print('error: authorization=synthetic-sensitive-value'); sys.exit(2)"
        )
        with self.assertRaises(EnvironmentFailure) as context:
            run_command(
                [sys.executable, "-c", script],
                operation_dir=self.operation,
                env=install_environment(self.cache, self.operation),
                cancel=threading.Event(),
                timeout=3,
            )
        error = context.exception
        self.assertEqual(error.code, "network_error")
        serialized = json.dumps(error.tail)
        self.assertIn("connection refused", serialized)
        for forbidden in (
            "private-value",
            "synthetic-sensitive-value",
            "/private/operator",
            "https://",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertLess(len(serialized), 6500)

    def test_tail_is_bounded_and_fragmented_secret_or_giant_lines_are_not_kept(self):
        tail = DiagnosticTail()
        tail.feed(b"error: to")
        tail.feed(b"ken=synthetic-value\n")
        tail.feed(b"error: " + b"x" * 10000)
        tail.feed(b"x" * 10000 + b"\n")
        for _ in range(100):
            tail.feed(b"error: No solution found when resolving pinned packages\n")
        failure = tail.failure()
        self.assertEqual(failure.code, "dependency_resolution")
        self.assertEqual(len(failure.tail), 12)
        self.assertNotIn("synthetic-value", repr(failure.tail))
        self.assertNotIn("x" * 100, repr(failure.tail))
        self.assertEqual(
            failure_from_exception(InterruptedError()).code, "operation_cancelled"
        )
        self.assertEqual(
            failure_from_exception(TimeoutError()).code, "operation_timeout"
        )

    def test_nonfinite_command_lifetime_never_spawns(self):
        for value in (float("nan"), float("inf"), -1, 3601):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_command(
                    ["must-not-launch"],
                    operation_dir=self.operation,
                    env=install_environment(self.cache, self.operation),
                    cancel=threading.Event(),
                    timeout=value,
                )


class DownloadProgressTests(RecipeFixture):
    def test_streamed_bytes_and_cached_digest_have_honest_bounded_progress(self):
        data = b"x" * (2 * 1024 * 1024 + 100)
        digest = hashlib.sha256(data).hexdigest()
        opener = Mock()
        opener.open.return_value = io.BytesIO(data)
        events = []
        clock = iter(range(1000))
        with (
            patch(
                "patent_sar_extractor.workers.environment_assets.urllib.request.build_opener",
                return_value=opener,
            ),
            patch(
                "patent_sar_extractor.workers.environment_assets.time.monotonic",
                side_effect=lambda: next(clock),
            ),
        ):
            path = download(
                "https://files.pythonhosted.org/controlled-fixture",
                self.cache,
                size=len(data),
                sha256=digest,
                cancel=threading.Event(),
                progress=lambda received, total: events.append((received, total)),
            )
        self.assertEqual(path.read_bytes(), data)
        self.assertTrue(
            all(0 < received <= total == len(data) for received, total in events)
        )
        self.assertEqual(events[-1], (len(data), len(data)))
        self.assertGreater(len(events), 3)
        cached_events = []
        download(
            "https://files.pythonhosted.org/controlled-fixture",
            self.cache,
            size=len(data),
            sha256=digest,
            cancel=threading.Event(),
            progress=lambda received, total: cached_events.append((received, total)),
        )
        self.assertEqual(cached_events, [(len(data), len(data))])

    def test_cancelled_stream_does_not_report_complete_or_leave_own_partial(self):
        data = b"x" * (2 * 1024 * 1024)
        digest = hashlib.sha256(data).hexdigest()
        cancel = threading.Event()
        opener = Mock()
        opener.open.return_value = io.BytesIO(data)
        events = []

        def progress(received, total):
            events.append((received, total))
            cancel.set()

        with (
            patch(
                "patent_sar_extractor.workers.environment_assets.urllib.request.build_opener",
                return_value=opener,
            ),
            self.assertRaises(InterruptedError),
        ):
            download(
                "https://files.pythonhosted.org/controlled-fixture",
                self.cache,
                size=len(data),
                sha256=digest,
                cancel=cancel,
                progress=progress,
            )
        self.assertTrue(events and events[-1][0] < len(data))
        self.assertFalse(list(self.cache.iterdir()))


class LegacySegmentationTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("PATENTSAR_ENVIRONMENT_TEST_DECIMER_PYTHON"),
        "Explicit external recovered local model input required",
    )
    def test_real_legacy_h5_is_sha_verified_and_reused_without_modification(self):
        python = Path(os.environ["PATENTSAR_ENVIRONMENT_TEST_DECIMER_PYTHON"])
        weights = (
            python.parent.parent
            / "lib/python3.10/site-packages/decimer_segmentation/mask_rcnn_molecule.h5"
        )
        before = (weights.stat().st_size, weights.stat().st_mtime_ns)
        with tempfile.TemporaryDirectory(
            dir=os.environ.get("PATENTSAR_WEB_TEST_ROOT")
        ) as directory:
            config = segmentation_config(Path(directory), python)
        self.assertEqual(config, {"decimer_segmentation_models": str(weights)})
        self.assertEqual(before, (weights.stat().st_size, weights.stat().st_mtime_ns))
