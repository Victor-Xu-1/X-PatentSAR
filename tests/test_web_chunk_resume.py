"""Partial segmentation transport preserves content, not chemistry acceptance."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import fitz
from test_web_support import ExitRunner, WebFixture

from patent_sar_extractor import contracts as core
from patent_sar_extractor.application.stage_cache import (
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.application.structure_cache import (
    _load_reusable_structure_chunk,
    _structure_chunk_fingerprint,
)
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.web.attempts import ARTIFACTS, OCR_PATH, seed_checkpoints
from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.models import JobRequest
from patent_sar_extractor.web.pdf import copy_original
from patent_sar_extractor.web.service import WorkspaceService


class ChunkResumeTests(WebFixture, unittest.TestCase):
    def prepare_source(self):
        from patent_sar_extractor.core.page_ocr_cache import build_cache_metadata

        with fitz.open() as pdf:
            for _ in range(3):
                pdf.new_page(width=100, height=100).insert_text(
                    (5, 20), "Controlled checkpoint fixture"
                )
            pdf.save(self.pdf, incremental=False)
        service = WorkspaceService(self.state)
        project = service.add_pdf(
            copy_original(self.pdf, self.state / "uploads"), "source.pdf", None
        )
        queue = JobQueue(service, ExitRunner(), 30)
        job = queue.enqueue(project.id, JobRequest())
        spec = decode_spec(service.store.job(job.id)["spec"])
        source = Path(spec.output_dir)
        write_json_atomic(
            source / OCR_PATH,
            {
                "metadata": build_cache_metadata(spec.pdf_path, 3),
                "page_texts": {"0": "source"},
                "ocr_line_map": {},
            },
        )
        dependencies = []
        for stage in ("classify", "activity", "locate"):
            path, schema, version = ARTIFACTS[stage]
            payload = {
                **core.artifact_identity(schema, version),
                **{
                    "classify": {"page_count": 3},
                    "activity": {"rows": [], "active_cpds": []},
                    "locate": {"selected_pages": [0, 1, 2], "crop_regions": {}},
                }[stage],
            }
            write_json_atomic(source / path, payload)
            _write_step_manifest(
                str(source / path),
                _step_fingerprint(
                    stage, pdf_path=spec.pdf_path, dependencies=dependencies, params={}
                ),
            )
            dependencies.append(str(source / path))
        write_json_atomic(source / "structure_pages/crop_regions.json", {})
        write_json_atomic(
            source / "pipeline_summary.json",
            {
                **core.artifact_identity(
                    core.RUN_SUMMARY_SCHEMA, core.RUN_SUMMARY_SCHEMA_VERSION
                ),
                "status": "failed",
                "steps": {
                    **{
                        stage: {"status": "ok"}
                        for stage in ("classify", "activity", "locate")
                    },
                    "structures": {"status": "failed"},
                },
            },
        )
        for index in (0, 2):
            chunk = source / f"structures/.chunks/chunk_{index:03d}"
            chunk.mkdir(parents=True)
            image = chunk / "structure.png"
            with fitz.open(spec.pdf_path) as pdf:
                pdf[index].get_pixmap().save(image)
            write_json_atomic(
                chunk / "metadata.json",
                {
                    **core.artifact_identity(
                        core.STRUCTURES_SCHEMA, core.STRUCTURES_SCHEMA_VERSION
                    ),
                    "structures": [
                        {
                            "structure_id": f"raw-{index}",
                            "page_no": index + 1,
                            "image_path": str(image),
                        }
                    ],
                },
            )
            fp = _structure_chunk_fingerprint(
                pdf_path=spec.pdf_path,
                dependencies=[
                    str(source / ARTIFACTS["locate"][0]),
                    str(source / "structure_pages/crop_regions.json"),
                ],
                chunk_index=index,
                chunk_pages=[index],
                chunk_size=1,
                crop_regions={},
                gpu_mode="off",
            )
            _write_step_manifest(str(chunk / "metadata.json"), fp)
        return spec, source

    def test_completed_chunks_survive_an_unfinished_segmentation_stage(self):
        spec, source = self.prepare_source()
        target = self.root / "new-attempt"
        before = (source / "structures/.chunks/chunk_000/metadata.json").read_bytes()
        seed_checkpoints(spec, target)
        self.assertFalse((target / "structures/metadata.json").exists())
        self.assertFalse((target / "pipeline_summary.json").exists())
        for index in (0, 2):
            chunk = target / f"structures/.chunks/chunk_{index:03d}"
            fp = _structure_chunk_fingerprint(
                pdf_path=spec.pdf_path,
                dependencies=[
                    str(target / ARTIFACTS["locate"][0]),
                    str(target / "structure_pages/crop_regions.json"),
                ],
                chunk_index=index,
                chunk_pages=[index],
                chunk_size=1,
                crop_regions={},
                gpu_mode="off",
            )
            payload = _load_reusable_structure_chunk(str(chunk), fp)
            self.assertIsNotNone(payload)
            original_image = (
                source / f"structures/.chunks/chunk_{index:03d}/structure.png"
            )
            copied_image = Path(payload["structures"][0]["image_path"])
            self.assertEqual(copied_image.read_bytes(), original_image.read_bytes())
            self.assertNotEqual(
                copied_image.stat().st_ino, original_image.stat().st_ino
            )
        self.assertFalse((target / "structures/.chunks/chunk_001").exists())
        self.assertEqual(
            (source / "structures/.chunks/chunk_000/metadata.json").read_bytes(), before
        )

    def test_mismatched_page_partition_is_not_promoted(self):
        spec, source = self.prepare_source()
        path = source / "structures/.chunks/chunk_000/metadata.json.manifest.json"
        manifest = json.loads(path.read_text())
        from patent_sar_extractor.application.stage_cache import _stable_digest

        manifest["fingerprint"]["params"]["chunk_pages"] = [2]
        manifest["fingerprint"]["params_digest"] = _stable_digest(
            manifest["fingerprint"]["params"]
        )
        write_json_atomic(path, manifest)
        target = self.root / "mismatch-attempt"
        seed_checkpoints(spec, target)
        self.assertFalse((target / "structures/.chunks/chunk_000").exists())
        self.assertTrue(
            (target / "structures/.chunks/chunk_002/metadata.json").exists()
        )


if __name__ == "__main__":
    unittest.main()
