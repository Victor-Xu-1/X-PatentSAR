"""Saved-source progress while the real window child is still alive, without ML."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from patent_sar_extractor.application.stage_cache import _write_step_manifest
from patent_sar_extractor.application.structure_checkpoint_observer import (
    WindowCheckpointObserver,
)
from patent_sar_extractor.application.structure_progress import StructureProgress
from patent_sar_extractor.application.structure_window import execute_missing_windows
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core import env_runner
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.stages import read_progress
from tests.structure_window_controls import make_window, native_worker, save_chunk


class LiveWindowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="live-window-controls-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pdf, self.output, self.jobs = make_window(self.root)

    def execute(self, runner, on_saved, *, script="generated-control.py"):
        return execute_missing_windows(
            self.jobs,
            runner=runner,
            pdf=str(self.pdf),
            root=str(self.output),
            script=script,
            patent_id="GENERATED-CHECKPOINT-CONTROL",
            crop_regions="",
            environment={},
            cwd=str(self.root),
            on_saved=on_saved,
        )

    @unittest.skipUnless(os.name == "posix", "Native Linux/WSL worker pipes")
    def test_native_checkpoint_is_published_before_the_same_child_can_continue(self):
        script = native_worker(self.root)
        progress = StructureProgress(str(self.output), [0, 1, 2])
        observed = []

        def saved(pages):
            pid = json.loads((self.output / "owned-pid.json").read_text())["pid"]
            if not observed:
                # The child cannot pass its second extraction until this first
                # callback acknowledges a real, already sealed checkpoint.
                self.assertTrue(Path(f"/proc/{pid}").exists())
            progress.saved(pages)
            observed.append(read_progress(SafeFiles(self.root), "structures").completed)
            (self.output / "observed.ack").write_text("seen", encoding="utf-8")

        def runner(*args, **kwargs):
            return env_runner.run_in_env(*args, **{**kwargs, "timeout": 10})

        with (
            patch.dict(os.environ, {"DECIMER_PYTHON": sys.executable}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            produced = self.execute(runner, saved, script=str(script))
        self.assertEqual(observed, [1, 2, 3])
        self.assertEqual(len(produced), 3)
        self.assertNotIn("core_accepted", next(iter(produced.values())))

    def test_untrusted_log_counts_never_become_progress_and_saved_chunk_is_deduplicated(
        self,
    ):
        observed = []

        def runner(*_args, **kwargs):
            line = kwargs.get("on_line")
            self.assertIsNotNone(line)
            line("9999 pages completed\n")
            self.assertEqual(observed, [])
            save_chunk(self.jobs[0])
            for _ in range(4):
                line("any bounded worker line\n")
            self.assertEqual(observed, [[0]])
            return CompletedProcess([], 1)

        with self.assertRaisesRegex(RuntimeError, "completed chunks retained"):
            self.execute(runner, observed.append)
        self.assertEqual(observed, [[0]])

    def test_new_metadata_waits_for_a_fresh_matching_manifest(self):
        observed = []
        job = self.jobs[0]
        path = save_chunk(job)

        def runner(*_args, **kwargs):
            line = kwargs.get("on_line")
            self.assertIsNotNone(line)
            save_chunk(job, seal=False)
            line("fresh output, old seal\n")
            self.assertEqual(observed, [])
            _write_step_manifest(str(path), job["fingerprint"])
            line("fresh output and seal\n")
            self.assertEqual(observed, [[0]])
            return CompletedProcess([], 1)

        with self.assertRaisesRegex(RuntimeError, "completed chunks retained"):
            self.execute(runner, observed.append)
        self.assertEqual(observed, [[0]])

    def test_final_validation_does_not_accept_a_changed_previously_observed_chunk(self):
        observed = []

        def runner(*_args, **kwargs):
            line = kwargs.get("on_line")
            self.assertIsNotNone(line)
            for job in self.jobs:
                save_chunk(job)
            line("saved\n")
            self.assertEqual(observed, [[0], [1], [2]])
            path = Path(self.jobs[0]["output"]) / "metadata.json"
            write_json_atomic(path, {"source_inventory": "changed"})
            return CompletedProcess([], 0)

        with self.assertRaisesRegex(RuntimeError, "completed chunks retained"):
            self.execute(runner, observed.append)

    def test_progress_does_not_borrow_a_different_fingerprint_page_list(self):
        job = self.jobs[0]
        observer = WindowCheckpointObserver([{**job, "pages": [1]}], self.fail)
        save_chunk(job)
        observer.on_line("not a work receipt\n")
        self.assertEqual(observer.collect(terminal=True), {})

    def test_fresh_manifest_cannot_turn_unchanged_old_metadata_into_new_work(self):
        job = self.jobs[0]
        path = save_chunk(job)
        observed = []
        observer = WindowCheckpointObserver([job], observed.append)
        _write_step_manifest(str(path), job["fingerprint"])
        observer.on_line("new seal, old output\n")
        self.assertEqual(observed, [])
        self.assertEqual(observer.collect(terminal=True), {})

    def test_invalid_or_foreign_source_never_counts_and_later_valid_seal_is_observed(
        self,
    ):
        job = self.jobs[0]
        observed = []
        observer = WindowCheckpointObserver([job], observed.append)
        path = save_chunk(job, changes={"failed_pages": ["controlled SDK failure"]})
        observer.on_line("saved says nothing about validity\n")
        self.assertEqual(observed, [])
        save_chunk(job)
        _write_step_manifest(str(path), {**job["fingerprint"], "pdf_sha256": "b" * 64})
        observer.on_line("foreign fingerprint\n")
        self.assertEqual(observed, [])
        _write_step_manifest(str(path), job["fingerprint"])
        observer.on_line("matching evidence\n")
        self.assertEqual(observed, [[0]])

    def test_unchanged_output_lines_do_not_repeat_the_checkpoint_parser(self):
        from patent_sar_extractor.application.structure_cache import (
            _load_reusable_structure_chunk,
        )

        job = self.jobs[0]
        observed = []
        observer = WindowCheckpointObserver([job], observed.append)
        save_chunk(job)
        with patch(
            "patent_sar_extractor.application.structure_checkpoint_observer._load_reusable_structure_chunk",
            wraps=_load_reusable_structure_chunk,
        ) as read:
            for _ in range(100):
                observer.on_line("repeated bounded SDK line\n")
            self.assertEqual(read.call_count, 1)
            self.assertEqual(len(observer.collect(terminal=True)), 1)
            self.assertEqual(read.call_count, 2)
        self.assertEqual(observed, [[0]])


if __name__ == "__main__":
    unittest.main()
