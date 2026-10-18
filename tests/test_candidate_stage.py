"""Actual coordinator/worker protocol with synthetic originals and controlled OCSR."""

import copy
import hashlib
import os
import shutil
import sys
import unittest
from argparse import Namespace
from subprocess import CompletedProcess
from unittest.mock import patch

import fitz
import test_candidate_observations as source_controls
from PIL import Image

from patent_sar_extractor import contracts
from patent_sar_extractor.application import stage_smiles
from patent_sar_extractor.application.pipeline_context import PipelineContext
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.core.binding_artifacts import write_binding_result
from patent_sar_extractor.core.ocsr import run_smiles
from patent_sar_extractor.core.ocsr.candidate_coverage import candidate_coverage_errors
from patent_sar_extractor.core.structure_inventory import inventory_packet
from patent_sar_extractor.smiles_artifact import smiles_artifact_is_current


class NoOptionalModel:
    def __init__(self, *, env_extra=None):
        self.env_extra = env_extra

    def is_available(self):
        return False


class CandidateStageControls(source_controls.CandidateSourceControls):
    def setUp(self):
        super().setUp()
        environment = patch.dict(
            os.environ, {"PATENTSAR_PROGRESS_ROOT": "", "PATENTSAR_PROGRESS_STAGE": ""}
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.output = self.root / "stage-output"
        self.output.mkdir()
        self.metadata_path = self.output / "structures" / "metadata.json"
        self.metadata_path.parent.mkdir()
        for source in self.metadata["structures"]:
            original = self.root / source["image_path"]
            copied = self.metadata_path.parent / original.name
            shutil.copyfile(original, copied)
            source["image_path"] = str(copied)
        write_json_atomic(self.metadata_path, self.metadata)
        write_json_atomic(str(self.metadata_path) + ".manifest.json", self.manifest)
        directory = self.output / "structure_bindings"
        self.bindings = write_binding_result(
            directory,
            patent_id="Synthetic",
            bindings=[],
            detected_style="unassigned_originals",
            include_intermediates=False,
            total_structures=2,
            total_compound_blocks=0,
            table_pages=[],
            table_covered_count=0,
            no_binding=[],
            unbound_pages=[],
            original_pdf_sha256=self.original_sha,
        )
        self.bind_path = directory / "bindings.json"
        self.invocations = []

    def state(self):
        progress = PipelineProgress()
        log = {
            **contracts.artifact_identity(
                contracts.RUN_SUMMARY_SCHEMA, contracts.RUN_SUMMARY_SCHEMA_VERSION
            ),
            "steps": {},
            "main_chain": list(contracts.CORE_STAGE_ORDER),
            "status": "running",
        }
        progress.bind(str(self.output), log)
        return PipelineContext(
            args=Namespace(pdf=str(self.pdf), gpu_mode="off", smiles_workers=1),
            progress=progress,
            base_dir=str(self.output),
            pipeline_log=log,
            step_dirs={"smiles": str(self.output / "smiles")},
            structures_json=str(self.metadata_path),
            bind_json=str(self.bind_path),
            bind_payload=self.bindings,
            n_bound=0,
        )

    def execute(self, state):
        def worker(name, script, **kwargs):
            self.assertEqual(name, "smiles_engine")
            arguments = kwargs["args"]
            self.assertIn("--structures", arguments)
            self.assertIn("--source-pdf", arguments)
            self.assertNotIn("--include-unbound", arguments)
            self.invocations.append(arguments)
            with patch.object(sys, "argv", ["worker", *arguments]):
                run_smiles.main()
            return CompletedProcess([], 0, "", "")

        with (
            patch.object(stage_smiles, "run_in_env", side_effect=worker),
            patch.object(stage_smiles, "_gpu_env_extra", return_value={}),
            patch.object(
                stage_smiles, "DECIMEREngine", source_controls.ControlledDecimer
            ),
            patch.object(stage_smiles, "MolScribeEngine", NoOptionalModel),
            patch.dict(
                "patent_sar_extractor.core.ocsr.smiles_converter.ENGINE_MAP",
                {"decimer": source_controls.ControlledDecimer},
            ),
        ):
            stage_smiles.execute_smiles(state)


class CandidateStageTests(CandidateStageControls, unittest.TestCase):
    def test_main_chain_observes_original_images_when_no_printed_id_is_proved(self):
        state = self.state()
        self.execute(state)
        artifact = load_json(state.smiles_json, {})
        self.assertTrue(
            smiles_artifact_is_current(artifact, require_all_candidates=True)
        )
        self.assertEqual(artifact["records"], [])
        self.assertEqual([r["cpd_id"] for r in artifact["candidate_records"]], ["", ""])
        self.assertEqual(len(self.invocations), 1)
        stage = state.pipeline_log["steps"]["smiles"]
        self.assertEqual(stage["candidate_total"], 2)
        self.assertEqual(stage["execution_status"], "completed")
        self.assertEqual(stage["status"], "failed")
        self.assertTrue(state.scientific_errors["smiles"])

    def test_empty_detected_inventory_does_not_start_a_model_or_claim_products(self):
        self.pdf = self.root / "empty-original.pdf"
        with fitz.open() as document:
            for _ in range(3):
                document.new_page(width=200, height=200)
            document.save(self.pdf)
        original_sha = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.metadata.update(
            structures=[],
            total_structures=0,
            source_inventory=inventory_packet(
                3,
                [
                    {
                        "page_no": page,
                        "status": "detected",
                        "scope": "full_page",
                        "candidates": 0,
                    }
                    for page in (1, 2, 3)
                ],
            ),
        )
        self.manifest["fingerprint"]["pdf_sha256"] = original_sha
        write_json_atomic(self.metadata_path, self.metadata)
        write_json_atomic(str(self.metadata_path) + ".manifest.json", self.manifest)
        self.bindings["source_reference_scope"]["original_pdf_sha256"] = original_sha
        write_json_atomic(self.bind_path, self.bindings)
        state = self.state()
        self.execute(state)
        self.assertEqual(self.invocations, [])
        stage = state.pipeline_log["steps"]["smiles"]
        self.assertEqual(stage["total"], 0)
        self.assertEqual(stage["status"], "failed")
        self.assertEqual(stage["execution_status"], "not_started")
        self.assertTrue(state.scientific_errors["smiles"])
        artifact = load_json(state.smiles_json, {})
        self.assertTrue(
            smiles_artifact_is_current(artifact, require_all_candidates=True)
        )
        self.assertEqual(artifact["candidate_records"], [])

    def test_resume_reuses_complete_observations_without_rerunning_the_model(self):
        first = self.state()
        self.execute(first)
        second = self.state()
        self.execute(second)
        self.assertEqual(len(self.invocations), 1)
        self.assertTrue(second.progress.checkpoint_reused)
        self.assertEqual(second.pipeline_log["steps"]["smiles"]["candidate_total"], 2)
        self.assertTrue(second.scientific_errors["smiles"])

    def test_final_qa_replays_complete_source_inputs_instead_of_trusting_a_saved_flag(
        self,
    ):
        state = self.state()
        self.execute(state)
        artifact = load_json(state.smiles_json, {})
        arguments = (
            self.output,
            {"input_pdf": str(self.pdf)},
            self.metadata,
            self.bindings,
        )
        self.assertEqual(candidate_coverage_errors(*arguments, artifact), [])
        self.assertTrue(
            state.scientific_errors["smiles"],
            "Complete observations do not invent numbered products",
        )
        omitted = copy.deepcopy(artifact)
        omitted["candidate_records"].pop()
        self.assertTrue(candidate_coverage_errors(*arguments, omitted))
        no_inventory = copy.deepcopy(artifact)
        no_inventory["candidate_inventory"] = None
        no_inventory["candidate_records"] = []
        no_inventory["recognition_input_scope"] = "proved_sources_only"
        self.assertTrue(candidate_coverage_errors(*arguments, no_inventory))
        Image.new("RGB", (120, 80), "black").save(
            self.metadata["structures"][1]["image_path"]
        )
        self.assertTrue(candidate_coverage_errors(*arguments, artifact))
