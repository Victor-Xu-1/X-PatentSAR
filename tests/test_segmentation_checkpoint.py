"""Actual window/manifest code with native PDF controls and a non-model extractor."""

from __future__ import annotations

import unittest
from pathlib import Path

import test_source_order_checkpoints as controls
from test_web_support import WebFixture

from patent_sar_extractor import contracts as core
from patent_sar_extractor.application.structure_cache import (
    _load_reusable_structure_chunk,
    _structure_chunk_fingerprint,
)
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.workers.segmentation_window import execute_window


class SegmentationCheckpointTests(WebFixture, unittest.TestCase):
    def plan(self):
        spec, source = controls.SourceOrderCheckpointTests.source(self)
        root = source / "structures"
        jobs, fingerprints = [], []
        for index in range(2):
            output = root / ".chunks" / f"chunk_{index:03d}"
            output.mkdir(parents=True, exist_ok=True)
            manifest = output / "metadata.json.manifest.json"
            if manifest.exists():
                manifest.unlink()  # This test-created control must be sealed anew.
            fingerprint = _structure_chunk_fingerprint(
                pdf_path=spec.pdf_path,
                dependencies=[
                    str(source / "structure_pages/locator.json"),
                    str(source / "structure_pages/crop_regions.json"),
                ],
                chunk_index=index,
                chunk_pages=[index],
                chunk_size=1,
                crop_regions={},
                gpu_mode="off",
            )
            path = output / core.SEGMENTATION_INPUT_FINGERPRINT_FILE
            write_json_atomic(path, fingerprint)
            jobs.append(
                {"pages": [index], "output": str(output), "fingerprint_file": str(path)}
            )
            fingerprints.append(fingerprint)
        plan = root / ".chunks/window-control.json"
        write_json_atomic(
            plan,
            {
                "schema": core.schema_ref(
                    core.SEGMENTATION_WINDOW_SCHEMA,
                    core.SEGMENTATION_WINDOW_SCHEMA_VERSION,
                ),
                "jobs": jobs,
            },
        )
        return spec, source, root, plan, jobs, fingerprints

    @staticmethod
    def produced(output):
        write_json_atomic(
            Path(output) / "metadata.json",
            {
                **core.artifact_identity(
                    core.STRUCTURES_SCHEMA, core.STRUCTURES_SCHEMA_VERSION
                ),
                "total_structures": 0,
                "structures": [],
                "failed_pages": [],
            },
        )

    def test_first_chunk_is_sealed_before_a_later_chunk_interrupts(self):
        spec, _source, root, plan, jobs, fingerprints = self.plan()
        initialized = []

        def extract(_pdf, pages, output, _regions, **kwargs):
            initialized.append(kwargs["initialize_model"])
            if pages == [1]:
                raise RuntimeError("Controlled later interruption")
            self.produced(output)

        with self.assertRaisesRegex(RuntimeError, "later interruption"):
            execute_window(extract, str(plan), spec.pdf_path, str(root), "", "CONTROL")
        self.assertEqual(initialized, [True, False])
        self.assertIsNotNone(
            _load_reusable_structure_chunk(jobs[0]["output"], fingerprints[0])
        )
        self.assertFalse(
            (Path(jobs[1]["output"]) / "metadata.json.manifest.json").exists()
        )

    def test_foreign_or_changed_input_never_initializes_the_model(self):
        spec, _source, root, plan, jobs, fingerprints = self.plan()
        path = Path(jobs[0]["fingerprint_file"])
        write_json_atomic(path, {**fingerprints[0], "pdf_sha256": "0" * 64})
        calls = []
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            execute_window(
                lambda *args, **kwargs: calls.append(args),
                str(plan),
                spec.pdf_path,
                str(root),
                "",
                "CONTROL",
            )
        self.assertEqual(calls, [])
        write_json_atomic(path, fingerprints[0])
        jobs[0]["fingerprint_file"] = str(self.root / "outside.json")
        write_json_atomic(
            plan,
            {
                "schema": core.schema_ref(
                    core.SEGMENTATION_WINDOW_SCHEMA,
                    core.SEGMENTATION_WINDOW_SCHEMA_VERSION,
                ),
                "jobs": jobs,
            },
        )
        with self.assertRaisesRegex(ValueError, "owned chunk"):
            execute_window(
                lambda *args, **kwargs: calls.append(args),
                str(plan),
                spec.pdf_path,
                str(root),
                "",
                "CONTROL",
            )
        self.assertEqual(calls, [])

    def test_dependency_change_during_extraction_cannot_seal_a_checkpoint(self):
        spec, source, root, plan, jobs, _fingerprints = self.plan()

        def extract(_pdf, _pages, output, _regions, **kwargs):
            self.produced(output)
            write_json_atomic(
                source / "structure_pages/crop_regions.json", {"changed": {}}
            )

        with self.assertRaisesRegex(ValueError, "partition"):
            execute_window(extract, str(plan), spec.pdf_path, str(root), "", "CONTROL")
        self.assertFalse(
            (Path(jobs[0]["output"]) / "metadata.json.manifest.json").exists()
        )
