"""Native PDF/checkpoint controls for source-first resume, never chemistry gold."""

from __future__ import annotations

import hashlib
import json
import unittest
import uuid
from argparse import Namespace
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import fitz
from test_web_support import WebFixture

from patent_sar_extractor import contracts as core
from patent_sar_extractor.application.pipeline_context import PipelineContext
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.application.stage_cache import (
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.application.stage_structures import execute_structures
from patent_sar_extractor.application.structure_cache import (
    _load_reusable_structure_chunk,
    _structure_chunk_fingerprint,
)
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.page_ocr_cache import build_cache_metadata
from patent_sar_extractor.web.attempts import ARTIFACTS, OCR_PATH, seed_checkpoints
from patent_sar_extractor.web.processes import RunSpec


class SourceOrderCheckpointTests(WebFixture, unittest.TestCase):
    def source(self):
        pdf = self.root / "native-three-page-control.pdf"
        with fitz.open() as doc:
            for index in range(3):
                doc.new_page().insert_text((70, 80), f"Controlled native page {index}")
            doc.save(pdf)
        root = self.root / "source-run"
        root.mkdir(mode=0o700)
        spec = RunSpec(
            uuid.uuid4().hex,
            uuid.uuid4().hex,
            str(pdf),
            str(root),
            "CONTROL",
            hashlib.sha256(pdf.read_bytes()).hexdigest(),
        )
        with fitz.open(pdf) as doc:
            texts = {str(index): page.get_text() for index, page in enumerate(doc)}
            image = doc[0].get_pixmap(clip=fitz.Rect(60, 60, 270, 140)).tobytes("png")
        write_json_atomic(
            root / OCR_PATH,
            {
                "metadata": build_cache_metadata(str(pdf)),
                "page_texts": texts,
                "ocr_line_map": {},
            },
        )
        classify = root / ARTIFACTS["classify"][0]
        write_json_atomic(
            classify,
            {
                **core.artifact_identity(
                    core.PAGE_CLASSIFICATION_SCHEMA,
                    core.PAGE_CLASSIFICATION_SCHEMA_VERSION,
                ),
                "page_count": 3,
                "ocr_cache_path": str(root / OCR_PATH),
            },
        )
        _write_step_manifest(
            str(classify),
            _step_fingerprint(
                "classify", pdf_path=str(pdf), params={"patent_id": "CONTROL"}
            ),
        )
        locator = root / ARTIFACTS["locate"][0]
        write_json_atomic(
            locator,
            {
                **core.artifact_identity(
                    core.STRUCTURE_LOCATION_SCHEMA,
                    core.STRUCTURE_LOCATION_SCHEMA_VERSION,
                ),
                "selected_pages": [0, 1, 2],
                "crop_regions": {},
                "coverage_policy": "all_evidence_backed_structures",
            },
        )
        _write_step_manifest(
            str(locator),
            _step_fingerprint(
                "locate",
                pdf_path=str(pdf),
                dependencies=[str(classify), str(root / OCR_PATH)],
                params={"control": True},
            ),
        )
        crop = root / "structure_pages/crop_regions.json"
        write_json_atomic(crop, {})
        chunk = root / "structures/.chunks/chunk_000"
        chunk.mkdir(parents=True, mode=0o700)
        (chunk / "structure.png").write_bytes(image)
        write_json_atomic(
            chunk / "metadata.json",
            {
                **core.artifact_identity(
                    core.STRUCTURES_SCHEMA, core.STRUCTURES_SCHEMA_VERSION
                ),
                "failed_pages": [],
                "total_structures": 1,
                "structures": [
                    {
                        "structure_id": "S0000",
                        "page_no": 1,
                        "bbox_pdf": [60, 60, 270, 140],
                        "image_path": str(chunk / "structure.png"),
                    }
                ],
            },
        )
        _write_step_manifest(
            str(chunk / "metadata.json"),
            _structure_chunk_fingerprint(
                pdf_path=str(pdf),
                dependencies=[str(locator), str(crop)],
                chunk_index=0,
                chunk_pages=[0],
                chunk_size=1,
                crop_regions={},
                gpu_mode="off",
            ),
        )
        write_json_atomic(
            root / "pipeline_summary.json",
            {
                **core.artifact_identity(
                    core.RUN_SUMMARY_SCHEMA, core.RUN_SUMMARY_SCHEMA_VERSION
                ),
                "status": "running",
                "main_chain": list(core.CORE_STAGE_ORDER),
                "steps": {
                    "classify": {"status": "ok"},
                    "locate": {"status": "ok"},
                    "structures": {"status": "running"},
                },
            },
        )
        return spec, root

    def test_artifact_transport_order_derives_from_the_single_core_registry(self):
        self.assertEqual(
            list(ARTIFACTS),
            [name for name in core.CORE_STAGE_ORDER if name in ARTIFACTS],
        )

    def test_before_activity_saved_chunk_rebases_and_cli_does_not_repeat_it(self):
        spec, source = self.source()
        original = {
            str(path.relative_to(source)): path.read_bytes()
            for path in source.rglob("*")
            if path.is_file()
        }
        target = self.root / "new-attempt"
        seed_checkpoints(spec, target)
        self.assertTrue((target / "structure_pages/locator.json").is_file())
        self.assertTrue((target / "structure_pages/crop_regions.json").is_file())
        self.assertFalse((target / ARTIFACTS["activity"][0]).exists())
        expected = _structure_chunk_fingerprint(
            pdf_path=spec.pdf_path,
            dependencies=[
                str(target / ARTIFACTS["locate"][0]),
                str(target / "structure_pages/crop_regions.json"),
            ],
            chunk_index=0,
            chunk_pages=[0],
            chunk_size=1,
            crop_regions={},
            gpu_mode="off",
        )
        self.assertIsNotNone(
            _load_reusable_structure_chunk(
                str(target / "structures/.chunks/chunk_000"), expected
            )
        )
        log = {
            "main_chain": list(core.CORE_STAGE_ORDER),
            "steps": {},
            "status": "running",
        }
        progress = PipelineProgress()
        progress.bind(str(target), log)
        state = PipelineContext(
            args=Namespace(pdf=spec.pdf_path, gpu_mode="off"),
            progress=progress,
            patent_id="CONTROL",
            base_dir=str(target),
            step_dirs={"structures": str(target / "structures")},
            pipeline_log=log,
            structure_pages=[0, 1, 2],
            locator={"crop_regions": {}},
            locate_json=str(target / ARTIFACTS["locate"][0]),
            crop_regions_json=str(target / "structure_pages/crop_regions.json"),
        )
        requested = []

        def worker(_environment, _script, *, args, **kwargs):
            plan = json.loads(Path(args[args.index("--batch-plan") + 1]).read_text())
            for job in plan["jobs"]:
                requested.extend(job["pages"])
                write_json_atomic(
                    Path(job["output"]) / "metadata.json",
                    {
                        **core.artifact_identity(
                            core.STRUCTURES_SCHEMA, core.STRUCTURES_SCHEMA_VERSION
                        ),
                        "total_structures": 1,
                        "failed_pages": [],
                        "structures": [
                            {"structure_id": "S0000", "page_no": job["pages"][0] + 1}
                        ],
                    },
                )
                _write_step_manifest(
                    str(Path(job["output"]) / "metadata.json"),
                    json.loads(Path(job["fingerprint_file"]).read_text()),
                )
            return CompletedProcess([], 0)

        with (
            patch(
                "patent_sar_extractor.application.stage_structures._structure_chunk_size",
                return_value=1,
            ),
            patch(
                "patent_sar_extractor.application.stage_structures.run_in_env",
                side_effect=worker,
            ),
        ):
            execute_structures(state)
        self.assertEqual(requested, [1, 2])
        counters = json.loads((target / "structures/progress.json").read_text())
        self.assertEqual(
            (counters["completed"], counters["total"], counters["cache_hits"]),
            (3, 3, 1),
        )
        self.assertEqual(
            original,
            {
                str(path.relative_to(source)): path.read_bytes()
                for path in source.rglob("*")
                if path.is_file()
            },
        )

    def test_changed_dependency_never_becomes_a_reusable_segmentation_chunk(self):
        spec, source = self.source()
        path = source / ARTIFACTS["locate"][0]
        payload = json.loads(path.read_text())
        write_json_atomic(path, {**payload, "selected_pages": [0, 1]})
        target = self.root / "rejected-attempt"
        seed_checkpoints(spec, target)
        self.assertFalse(
            (target / "structures/.chunks/chunk_000/metadata.json").exists()
        )
