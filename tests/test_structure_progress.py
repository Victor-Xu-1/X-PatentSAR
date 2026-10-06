"""Real saved-checkpoint counters, never time/pending-work percentages."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess

from patent_sar_extractor.application.stage_cache import _write_step_manifest
from patent_sar_extractor.application.structure_progress import StructureProgress
from patent_sar_extractor.application.structure_window import execute_missing_windows
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    STRUCTURES_SCHEMA,
    STRUCTURES_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.stages import read_progress


class StructureProgressTests(unittest.TestCase):
    def test_saved_reused_and_duplicate_pages_round_trip_through_api_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "structures"
            progress = StructureProgress(str(output), [0, 2, 7])
            self.assertEqual(read_progress(SafeFiles(root), "structures").completed, 0)
            progress.saved([0, 2], cached=True)
            progress.saved([2])  # Repeated publication cannot double-count.
            saved = read_progress(SafeFiles(root), "structures")
            self.assertEqual(
                (saved.completed, saved.total, saved.cache_hits), (2, 3, 2)
            )
            self.assertIsNone(saved.device)
            self.assertIsNone(saved.peak_rss_mb)
            progress.saved([7])
            self.assertEqual(read_progress(SafeFiles(root), "structures").completed, 3)
            self.assertIsNone(
                read_progress(SafeFiles(root))
            )  # No borrowed SMILES stats.
            self.assertIsNone(read_progress(SafeFiles(root), "../structures"))
            StructureProgress(
                str(output), [0, 2, 7]
            )  # New attempt resets copied telemetry.
            self.assertEqual(read_progress(SafeFiles(root), "structures").completed, 0)

    def test_invalid_or_foreign_pages_cannot_change_published_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            for pages in ([True], [0, 0], [-1], [1.5]):
                with self.subTest(pages=pages), self.assertRaises(ValueError):
                    StructureProgress(directory, pages)
            progress = StructureProgress(directory, [0, 2])
            original = progress.path.read_bytes()
            for pages in ([True], [1], [-1], [2.0]):
                with self.subTest(pages=pages), self.assertRaises(ValueError):
                    progress.saved(pages)
                self.assertEqual(progress.path.read_bytes(), original)

    def test_failed_window_reports_only_fresh_valid_saved_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = [
                {
                    "pages": [index],
                    "output": str(root / f"chunk_{index}"),
                    "fingerprint": {"control": index},
                }
                for index in range(3)
            ]
            observed = []

            def runner(_env, _script, **kwargs):
                plan = json.loads(Path(kwargs["args"][-1]).read_text())
                for index, job in enumerate(plan["jobs"]):
                    if index == 2:
                        continue  # Pending/missing data is not progress.
                    write_json_atomic(
                        Path(job["output"]) / "metadata.json",
                        {
                            **artifact_identity(
                                STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION
                            ),
                            "structures": [],
                            "failed_pages": ["controlled failure"]
                            if index == 1
                            else [],
                        },
                    )
                    if index == 0:
                        _write_step_manifest(
                            str(Path(job["output"]) / "metadata.json"),
                            json.loads(Path(job["fingerprint_file"]).read_text()),
                        )
                return CompletedProcess([], 1)

            with self.assertRaisesRegex(RuntimeError, "completed chunks retained"):
                execute_missing_windows(
                    jobs,
                    runner=runner,
                    pdf="control.pdf",
                    root=str(root),
                    script="control.py",
                    patent_id="CONTROL",
                    crop_regions="",
                    environment={},
                    cwd=directory,
                    on_saved=observed.append,
                )
            self.assertEqual(observed, [[0]])
            self.assertTrue((root / "chunk_0/metadata.json.manifest.json").is_file())
            self.assertFalse((root / "chunk_1/metadata.json.manifest.json").exists())

    def test_wrong_stage_malformed_and_boolean_payload_remain_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            progress = StructureProgress(str(root / "structures"), [0])
            payload = json.loads(progress.path.read_text())
            for changes in (
                {"stage": "smiles"},
                {"completed": True},
                {"completed": 2},
                {"cache_hits": 1},
            ):
                write_json_atomic(progress.path, {**payload, **changes})
                self.assertIsNone(read_progress(SafeFiles(root), "structures"))
