"""Bounded stage integration: activity absence never prevents segmentation."""

from __future__ import annotations

import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from patent_sar_extractor.application.pipeline_context import PipelineContext
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.application.stage_cache import (
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.application.stage_locate import execute_locate
from patent_sar_extractor.application.stage_structures import execute_structures
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    STRUCTURE_LOCATOR_VERSION,
    STRUCTURES_SCHEMA,
    STRUCTURES_SCHEMA_VERSION,
    artifact_identity,
)


class StructureStageCoverageTests(unittest.TestCase):
    def context(self, root: Path, pages: list[int]):
        pdf = root / "original.pdf"
        pdf.write_bytes(b"controlled content for a stage fingerprint")
        locator = root / "locator.json"
        write_json_atomic(locator, {"selected_pages": pages, "crop_regions": {}})
        crops = root / "crop_regions.json"
        write_json_atomic(crops, {})
        log = {"steps": {}, "main_chain": ["structures"], "status": "running"}
        progress = PipelineProgress()
        progress.bind(str(root), log)
        return PipelineContext(
            args=Namespace(pdf=str(pdf), gpu_mode="off"),
            progress=progress,
            patent_id="CONTROLLED",
            base_dir=str(root),
            step_dirs={"structures": str(root / "structures")},
            pipeline_log=log,
            active_cpds=[],
            locate_json=str(locator),
            crop_regions_json=str(crops),
            locator={"crop_regions": {}},
            structure_pages=pages,
        )

    @staticmethod
    def worker(_env, _script, *, args, **_kwargs):
        if "--batch-plan" in args:
            import json

            plan = json.loads(Path(args[args.index("--batch-plan") + 1]).read_text())
            for job in plan["jobs"]:
                StructureStageCoverageTests.worker(
                    _env,
                    _script,
                    args=[
                        "--output",
                        job["output"],
                        "--pages",
                        *map(str, job["pages"]),
                    ],
                )
                import json

                _write_step_manifest(
                    str(Path(job["output"]) / "metadata.json"),
                    json.loads(Path(job["fingerprint_file"]).read_text()),
                )
            return CompletedProcess([], 0)
        output = Path(args[args.index("--output") + 1])
        pages = [int(page) for page in args[args.index("--pages") + 1 :]]
        write_json_atomic(
            output / "metadata.json",
            {
                **artifact_identity(STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION),
                "patent_number": "CONTROLLED",
                "total_structures": len(pages),
                "structures": [
                    {
                        "structure_id": f"S{page}",
                        "page_no": page + 1,
                        "bbox": [1, 2, 3, 4],
                    }
                    for page in pages
                ],
            },
        )
        return CompletedProcess([], 0)

    def test_no_activity_still_runs_full_page_segmentation_and_reuses_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self.context(root, [0, 2])
            with patch(
                "patent_sar_extractor.application.stage_structures.run_in_env",
                side_effect=self.worker,
            ) as worker:
                execute_structures(state)
                self.assertEqual(worker.call_count, 1)
                self.assertNotIn("--crop-regions", worker.call_args.kwargs["args"])
                self.assertEqual(state.n_structures, 2)
                import json

                saved = json.loads(
                    (Path(state.step_dirs["structures"]) / "progress.json").read_text()
                )
                self.assertEqual(
                    (saved["completed"], saved["total"], saved["cache_hits"]), (2, 2, 0)
                )
                self.assertEqual(
                    state.pipeline_log["steps"]["structures"]["status"], "ok"
                )
                execute_structures(state)
                self.assertEqual(worker.call_count, 1)
                self.assertTrue(state.pipeline_log["steps"]["structures"]["from_cache"])
                saved = json.loads(
                    (Path(state.step_dirs["structures"]) / "progress.json").read_text()
                )
                self.assertEqual(
                    (saved["completed"], saved["total"], saved["cache_hits"]), (2, 2, 2)
                )

    def test_no_activity_chunking_retains_all_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = self.context(Path(temporary), [0, 2, 4])
            with (
                patch(
                    "patent_sar_extractor.application.stage_structures._structure_chunk_size",
                    return_value=2,
                ),
                patch(
                    "patent_sar_extractor.application.stage_structures.run_in_env",
                    side_effect=self.worker,
                ) as worker,
            ):
                execute_structures(state)
            self.assertEqual(worker.call_count, 1)
            self.assertIn("--batch-plan", worker.call_args.kwargs["args"])
            self.assertEqual(state.n_structures, 3)

    def test_worker_failure_is_not_hidden_by_empty_activity(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = self.context(Path(temporary), [0])
            with (
                patch(
                    "patent_sar_extractor.application.stage_structures.run_in_env",
                    return_value=CompletedProcess([], 1),
                ),
                self.assertRaisesRegex(RuntimeError, "structure extraction failed"),
            ):
                execute_structures(state)
            self.assertFalse(Path(state.structures_json + ".manifest.json").exists())

    def test_activity_narrowed_locator_checkpoint_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self.context(root, [0])
            state.pipeline_log["main_chain"] = ["locate", "structures"]
            state.progress.bind(str(root), state.pipeline_log)
            state.step_dirs["locate"] = str(root)
            output = root / "locator.json"
            old_fingerprint = _step_fingerprint(
                "locate",
                pdf_path=state.args.pdf,
                dependencies=[
                    state.classify_json,
                    state.act_json,
                    state.ocr_cache_path,
                ],
                params={
                    "active_cpds": [],
                    "locate_workers": 1,
                    "structure_locator_contract_version": STRUCTURE_LOCATOR_VERSION,
                },
            )
            _write_step_manifest(str(output), old_fingerprint)
            current = {
                "selected_pages": [0, 2],
                "crop_regions": {},
                "coverage_policy": "all_evidence_backed_structures",
            }

            def locate(_pdf, _classification, active, path, **_kwargs):
                self.assertEqual(active, [])
                write_json_atomic(path, current)
                return current

            with patch(
                "patent_sar_extractor.application.stage_locate.locate_structure_pages",
                side_effect=locate,
            ) as locator:
                execute_locate(state)
                self.assertEqual(locator.call_count, 1)
                self.assertEqual(state.structure_pages, [0, 2])
                self.assertFalse(state.progress.checkpoint_reused)
                execute_locate(state)
                self.assertEqual(locator.call_count, 1)
                self.assertTrue(state.progress.checkpoint_reused)


if __name__ == "__main__":
    unittest.main()
