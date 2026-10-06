from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.application.pipeline_context import PipelineContext
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.application.stage_bind import execute_bind
from patent_sar_extractor.application.stage_cache import _bindings_ocsr_digest
from patent_sar_extractor.application.stage_smiles import execute_smiles
from patent_sar_extractor.application.stage_structures import execute_structures
from patent_sar_extractor.smiles_artifact import build_smiles_artifact
from tests.test_source_led_export import run_fixture


class PipelineStageTests(unittest.TestCase):
    def test_printed_catalog_stage_runs_even_without_activity_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "original.pdf"
            pdf.write_bytes(b"controlled fingerprint input, not patent evidence")
            dependency = root / "observations.json"
            dependency.write_text("{}")
            progress = PipelineProgress()
            log = {"steps": {}, "main_chain": ["bind"], "status": "running"}
            progress.bind(str(root), log)
            context = PipelineContext(
                args=Namespace(pdf=str(pdf), bind_workers=1),
                progress=progress,
                patent_id="TEST",
                base_dir=str(root),
                step_dirs={"bind": str(root / "bindings")},
                pipeline_log=log,
                active_cpds=[],
                n_structures=1,
                structures_json=str(dependency),
                act_json=str(dependency),
                locate_json=str(dependency),
                ocr_cache_path=str(dependency),
            )
            run_fixture(root)
            producer_payload = json.loads((root / "structure_bindings/bindings.json").read_text())

            def producer(*args, **kwargs):
                path = Path(context.bind_json)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(producer_payload))
                return producer_payload
            with (
                patch(
                    "patent_sar_extractor.core.structure_binder.bind",
                    side_effect=producer,
                ) as binder,
            ):
                execute_bind(context)
            binder.assert_called_once()
            serialized = json.loads(Path(context.bind_json).read_text())
            self.assertEqual(serialized["compound_catalog"], producer_payload["compound_catalog"])
            self.assertEqual(context.n_bound, 2)
            self.assertEqual(log["steps"]["bind"]["status"], "ok")
            self.assertEqual(context.source_cpds, ["Compound 42", "Compound 42A"])

    def test_old_output_cannot_hide_nonzero_worker_exit_or_missing_current_output(self):
        from subprocess import CompletedProcess

        for returncode in (1, 0):
            with (
                self.subTest(returncode=returncode),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                pdf = root / "original.pdf"
                pdf.write_bytes(b"controlled original hash input")
                binding = root / "bindings.json"
                run_fixture(root)
                binding_payload = json.loads((root / "structure_bindings/bindings.json").read_text())
                binding.write_text(json.dumps(binding_payload))
                smiles = root / "smiles_results.json"
                smiles.write_text(
                    json.dumps(
                        build_smiles_artifact(
                            [
                                {
                                    "cpd_id": "Compound 1",
                                    "rdkit_valid": True,
                                    "canonical_smiles": "CCO",
                                }
                            ]
                        )
                    )
                )
                old = smiles.read_bytes()
                progress = PipelineProgress()
                log = {"steps": {}, "main_chain": ["smiles"], "status": "running"}
                progress.bind(str(root), log)
                context = PipelineContext(
                    args=Namespace(pdf=str(pdf), gpu_mode="off"),
                    progress=progress,
                    base_dir=str(root),
                    patent_id="TEST",
                    step_dirs={"smiles": str(root)},
                    pipeline_log=log,
                    active_cpds=["Compound 1"],
                    n_bound=2,
                    bind_json=str(binding),
                    bind_payload=binding_payload,
                )
                with (
                    patch(
                        "patent_sar_extractor.application.stage_smiles.DECIMEREngine.runtime_identity",
                        return_value={"fingerprint": "a" * 64},
                    ),
                    patch(
                        "patent_sar_extractor.application.stage_smiles.run_in_env",
                        return_value=CompletedProcess(
                            [], returncode, stdout="controlled worker", stderr=""
                        ),
                    ),
                    patch(
                        "patent_sar_extractor.application.stage_smiles._smiles_acceptance_errors",
                        return_value=[],
                    ),
                    self.assertRaises(RuntimeError),
                ):
                    execute_smiles(context)
                self.assertEqual(smiles.read_bytes(), old)
                self.assertFalse(Path(str(smiles) + ".manifest.json").exists())

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
