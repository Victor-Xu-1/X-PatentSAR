"""Binding source work is optional telemetry, never a source/chemical decision."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.application.binding_progress import BindingProgress
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    STAGE_PROGRESS_SCHEMA,
    STAGE_PROGRESS_SCHEMA_VERSION,
    schema_ref,
)
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.stages import read_progress, stages_from_summary


class BindingProgressReaderTests(unittest.TestCase):
    def test_summary_keeps_completed_source_work_separate_from_stage_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = BindingProgress(str(root / "structure_bindings"))
            writer("heading_bindings", 7, 7)
            for status, count in (("running", None), ("failed", 3), ("pending", None)):
                with self.subTest(status=status):
                    summary = {"steps": {"bind": {"status": status, "bound": count}}}
                    stage = next(
                        stage
                        for stage in stages_from_summary(summary, SafeFiles(root))
                        if stage.name == "bind"
                    )
                    self.assertEqual(stage.status, status)
                    self.assertEqual(stage.count, count)
                    if status == "pending":
                        self.assertIsNone(stage.progress)
                    else:
                        self.assertEqual(
                            (stage.progress.completed, stage.progress.total), (7, 7)
                        )
                        self.assertEqual(
                            stage.progress.source_phase, "heading_bindings"
                        )

    def test_browser_acceptance_uses_only_the_read_only_fixture(self):
        from tools.browser_fixture_mode import fixture_mode

        self.assertEqual(
            fixture_mode({"frontend/e2e/binding-source-progress.spec.ts"}), "read-only"
        )

    def test_binding_source_progress_uses_its_existing_artifact_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json_atomic(
                root / "structure_bindings/progress.json",
                {
                    "schema": schema_ref(
                        STAGE_PROGRESS_SCHEMA, STAGE_PROGRESS_SCHEMA_VERSION
                    ),
                    "stage": "bind",
                    "phase": None,
                    "source_phase": "caption_sources",
                    "completed": 2,
                    "total": 7,
                    "cache_hits": 0,
                    "failures": 0,
                    "device": None,
                    "peak_rss_mb": None,
                },
            )
            observed = read_progress(SafeFiles(root), "bind")
            self.assertIsNotNone(observed)
            self.assertEqual(observed.source_phase, "caption_sources")
            self.assertEqual((observed.completed, observed.total), (2, 7))
            self.assertIsNone(observed.phase)
            self.assertIsNone(read_progress(SafeFiles(root), "structures"))
            self.assertIsNone(read_progress(SafeFiles(root), "smiles"))

    def test_new_producer_resets_old_telemetry_and_publishes_real_phase_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = BindingProgress(str(root / "structure_bindings"))
            self.assertIsNone(read_progress(SafeFiles(root), "bind"))
            with patch(
                "patent_sar_extractor.application.binding_progress.time.monotonic",
                side_effect=[1.0, 1.1, 1.2, 1.7, 1.8, 1.9],
            ):
                writer("caption_sources", 0, 4)
                writer("caption_sources", 1, 4)
                writer("caption_sources", 2, 4)
                self.assertEqual(read_progress(SafeFiles(root), "bind").completed, 0)
                writer("caption_sources", 3, 4)
                self.assertEqual(read_progress(SafeFiles(root), "bind").completed, 3)
                writer("caption_sources", 4, 4)  # Completion always flushes.
                self.assertEqual(read_progress(SafeFiles(root), "bind").completed, 4)
                writer(
                    "numbered_sources", 0, 4
                )  # A real new phase, not a time estimate.
            self.assertEqual(
                read_progress(SafeFiles(root), "bind").source_phase, "numbered_sources"
            )
            BindingProgress(str(root / "structure_bindings"))
            self.assertIsNone(read_progress(SafeFiles(root), "bind"))

    def test_invalid_regressing_or_foreign_phase_cannot_change_saved_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = BindingProgress(str(Path(directory) / "structure_bindings"))
            writer("caption_sources", 0, 4)
            writer("caption_sources", 1, 4)
            original = writer.path.read_bytes()
            for values in (
                ("caption_sources", True, 4),
                ("caption_sources", 1, 4.0),
                ("caption_sources", 0, 4),
                ("caption_sources", 1, 5),
                ("caption_sources", 5, 4),
                ("caption_sources", -1, 4),
                ("numbered_sources", 0, 4),
                ("lead", 0, 4),
                ("heading_sources", 0, 1_000_001),
            ):
                with self.subTest(values=values), self.assertRaises(ValueError):
                    writer(*values)
                self.assertEqual(writer.path.read_bytes(), original)
            writer("caption_sources", 4, 4)
            writer("numbered_sources", 0, 4)
            with self.assertRaises(ValueError):
                writer("caption_sources", 4, 4)

    def test_malformed_wrong_stage_and_mixed_phase_observations_stay_unavailable(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = BindingProgress(str(root / "structure_bindings"))
            writer("caption_sources", 0, 4)
            original = json.loads(writer.path.read_text())
            for changes in (
                {"stage": "smiles"},
                {"source_phase": "lead"},
                {"source_phase": None},
                {"completed": True},
                {"completed": 5},
                {"phase": "recognition"},
                {"schema": schema_ref(STAGE_PROGRESS_SCHEMA, 999)},
            ):
                with self.subTest(changes=changes):
                    write_json_atomic(writer.path, original | changes)
                    self.assertIsNone(read_progress(SafeFiles(root), "bind"))
            write_json_atomic(
                root / "smiles/progress.json", original | {"stage": "smiles"}
            )
            self.assertIsNone(read_progress(SafeFiles(root), "smiles"))


if __name__ == "__main__":
    unittest.main()
