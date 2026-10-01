from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.application.pipeline_context import PipelineContext
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.application.stage_cache import _bindings_ocsr_digest
from patent_sar_extractor.application.stage_structures import execute_structures


class PipelineStageTests(unittest.TestCase):
    def test_empty_locator_never_invokes_segmentation_or_unbound_fingerprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            progress = PipelineProgress()
            log = {"steps": {}, "main_chain": ["structures"], "status": "running"}
            progress.bind(str(root), log)
            context = PipelineContext(
                args=Namespace(pdf="unused-original.pdf"),
                progress=progress,
                patent_id="TEST",
                step_dirs={"structures": str(root / "structures")},
                pipeline_log=log,
                active_cpds=["Compound 1"],
                structure_pages=[],
            )
            with patch(
                "patent_sar_extractor.application.stage_structures.run_in_env"
            ) as worker:
                execute_structures(context)
            worker.assert_not_called()
            self.assertEqual(context.n_structures, 0)
            self.assertEqual(log["steps"]["structures"]["status"], "empty")
            self.assertFalse(log["steps"]["structures"]["from_cache"])

    def test_image_content_change_invalidates_binding_to_ocsr_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "image.png"
            image.write_bytes(b"first")
            binding = root / "bindings.json"
            binding.write_text(
                json.dumps(
                    {
                        "final_bindings": [
                            {
                                "cpd": "Compound 1",
                                "structure_id": "S1",
                                "image_path": str(image),
                            }
                        ]
                    }
                )
            )
            initial = _bindings_ocsr_digest(str(binding))
            image.write_bytes(b"second-drawing")
            self.assertNotEqual(initial, _bindings_ocsr_digest(str(binding)))

    def test_stage_start_resets_only_real_checkpoint_reuse_fact(self):
        with tempfile.TemporaryDirectory() as temporary:
            progress = PipelineProgress()
            progress.bind(
                temporary, {"steps": {}, "main_chain": ["classify", "activity"]}
            )
            progress.start("classify")
            self.assertFalse(progress.checkpoint_reused)
            progress.mark_checkpoint_reused()
            self.assertTrue(progress.checkpoint_reused)
            progress.start("activity")
            self.assertFalse(progress.checkpoint_reused)
