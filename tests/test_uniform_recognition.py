"""Same source ownership/QC and metric path with or without measured activity."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import test_compound_catalog_view as catalog_tests
import test_corpus_predictions as corpus_tests
from recognition_source_support import complete_observation_artifact, observation
from test_prediction_support import PredictionFixture

from patent_sar_extractor.application.pipeline_context import PipelineContext
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.application.recognition_budget import recognition_timeout
from patent_sar_extractor.application.stage_cache import _bindings_ocsr_digest
from patent_sar_extractor.application.stage_smiles import execute_smiles
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.smiles_artifact import (
    smiles_artifact_is_current,
    smiles_records,
)
from patent_sar_extractor.web.acceptance import ARTIFACTS
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.exports import export_json
from patent_sar_extractor.web.prediction_worker import run_predictions


class UniformRecognitionTests(PredictionFixture, unittest.TestCase):
    def prepare(self, raw="CCO"):
        path, payload = catalog_tests.CompoundCatalogViewTests.catalog_run(self)
        artifact = complete_observation_artifact(
            payload,
            pdf=self.pdf,
            structures=self.run / "structures/metadata.json",
            binding_dir=path.parent,
            source_raw=raw,
            raw_by_owner={"Compound 8": raw},
        )
        (self.run / ARTIFACTS["smiles"][0]).write_text(json.dumps(artifact))
        self.service.refresh(self.project.id)
        return path, payload, artifact

    def test_numbered_without_activity_uses_same_recognition_and_all_six_properties(
        self,
    ):
        self.prepare()
        before = {p: p.read_bytes() for p in self.run.rglob("*") if p.is_file()}
        first, no_activity = self.service.results(self.project.id).items
        self.assertEqual(no_activity.id, "Compound 8")
        self.assertEqual(no_activity.activities, [])
        self.assertEqual(no_activity.record_kind, "structure_only")
        self.assertEqual(no_activity.smiles, first.smiles)
        self.assertEqual(no_activity.recognition.status, "valid")
        self.assertTrue(no_activity.redraw_image_url)
        row, _ = corpus_tests.CorpusPredictionTests.job(self)
        model = corpus_tests.ControlledAnalysis()
        run_predictions(self.service, model, row)
        self.assertEqual(model.inputs, [["CCO", "CCO"]])
        result = self.service.results(self.project.id)
        for item in result.items:
            self.assertEqual(item.admet.status, "complete")
            self.assertEqual(len(item.admet.properties), 6)
        exported = json.loads(
            b"".join(export_json(self.service.project(self.project.id), result.items))
        )
        self.assertTrue(exported["review_only"])
        self.assertEqual(exported["structure_only"], 1)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_rejected_source_does_not_acquire_smiles_or_model_properties(self):
        self.prepare(raw="CC*")
        no_activity = self.service.results(self.project.id).items[1]
        self.assertEqual(no_activity.recognition.status, "invalid")
        self.assertIsNone(no_activity.smiles)
        row, _ = corpus_tests.CorpusPredictionTests.job(self)
        model = corpus_tests.ControlledAnalysis()
        run_predictions(self.service, model, row)
        self.assertEqual(model.inputs, [["CCO"]])
        retained = self.service.results(self.project.id).items[1]
        self.assertEqual(retained.admet.status, "unavailable")
        self.assertEqual(retained.admet.properties, [])

    def test_missing_image_retains_explicit_unavailable_recognition(self):
        _, _, artifact = self.prepare()
        artifact["records"][1] = {
            **artifact["records"][1],
            "cpd_id": "Compound 8",
            "structure_id": "numbered-without-activity",
            "OCSR_status": "image_missing",
            "OCSR_quality_flag": "empty_prediction",
            "rdkit_valid": False,
            "raw_smiles": None,
            "canonical_smiles": None,
            "image_hash": None,
            "model_fingerprint": None,
            "OCSR_engine": None,
        }
        artifact["records"][1].pop("stereochemistry", None)
        (self.run / ARTIFACTS["smiles"][0]).write_text(json.dumps(artifact))
        self.service.refresh(self.project.id)
        item = self.service.results(self.project.id).items[1]
        self.assertEqual(item.recognition.status, "unavailable")
        self.assertIsNone(item.smiles)

    def test_rejected_active_source_uses_the_same_no_prediction_standard(self):
        _, payload, artifact = self.prepare()
        artifact["records"][0] = observation(
            payload["compound_catalog"]["entries"][0], "CC*"
        )
        (self.run / ARTIFACTS["smiles"][0]).write_text(json.dumps(artifact))
        self.service.refresh(self.project.id)
        row, _ = corpus_tests.CorpusPredictionTests.job(self)
        model = corpus_tests.ControlledAnalysis()
        run_predictions(self.service, model, row)
        self.assertEqual(model.inputs, [["CCO"]])
        first, no_activity = self.service.results(self.project.id).items
        self.assertEqual(first.admet.status, "unavailable")
        self.assertEqual(first.admet.error.code, "admet_recognition_rejected")
        self.assertEqual(first.admet.properties, [])
        self.assertEqual(no_activity.admet.status, "complete")

    def test_foreign_source_cannot_borrow_another_compounds_molecule(self):
        _, _, artifact = self.prepare()
        artifact["records"][1]["structure_id"] = "S0"
        (self.run / ARTIFACTS["smiles"][0]).write_text(json.dumps(artifact))
        with self.assertRaises(WebError) as rejected:
            self.service.refresh(self.project.id)
        self.assertEqual(rejected.exception.code, "invalid_source_recognition")

    def test_catalog_union_preserves_primary_order_and_recognizes_reprint_sources(self):
        _, payload = catalog_tests.CompoundCatalogViewTests.catalog_run(self)
        plan = recognition_inputs(payload)
        formal, sources = plan.formal, plan.supplemental
        self.assertEqual([item["cpd"] for item in formal], ["Compound 1", "Compound 8"])
        self.assertEqual(sources, [])
        self.assertNotIn("proved-reprint", [item["structure_id"] for item in sources])
        self.assertEqual(
            [item["structure_id"] for item in plan.reprints], ["proved-reprint"]
        )
        payload["final_bindings"] = []
        with self.assertRaisesRegex(ValueError, "authority"):
            recognition_inputs(payload)

    def test_conflicting_catalog_formal_owner_is_rejected_before_inference(self):
        _, payload = catalog_tests.CompoundCatalogViewTests.catalog_run(self)
        payload["final_bindings"] = [{"cpd": "Compound 1", "structure_id": "wrong"}]
        with self.assertRaisesRegex(ValueError, "authority"):
            recognition_inputs(payload)

    def test_source_only_image_content_changes_invalidate_recognition_checkpoint(self):
        path, payload = catalog_tests.CompoundCatalogViewTests.catalog_run(self)
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "other.png"
            other.write_bytes(b"first source observation")
            entry = payload["compound_catalog"]["entries"][1]
            entry["image_path"] = str(other)
            path.write_text(json.dumps(payload))
            initial = _bindings_ocsr_digest(str(path))
            other.write_bytes(b"changed source observation")
            self.assertNotEqual(initial, _bindings_ocsr_digest(str(path)))

    def test_single_converter_batch_covers_formal_and_no_activity_sources(self):
        from patent_sar_extractor.core.ocsr import run_smiles

        path, _ = catalog_tests.CompoundCatalogViewTests.catalog_run(self)
        batches = []

        class ControlledConverter:
            cache = None

            def __init__(self, **kwargs):
                self.assertions = kwargs
                self.engines = {}

            def convert_batch(self, bindings, **kwargs):
                batches.append([item["cpd"] for item in bindings])
                return [observation(item) for item in bindings]

        output = self.root / "controlled-smiles.json"
        with (
            patch.object(
                sys,
                "argv",
                [
                    "run_smiles",
                    "--input",
                    str(path),
                    "--structures",
                    str(self.run / "structures/metadata.json"),
                    "--source-pdf",
                    str(self.pdf),
                    "--output",
                    str(output),
                    "--csv-output",
                    str(self.root / "controlled.csv"),
                    "--cache",
                    str(self.root / "controlled-cache.sqlite"),
                    "--no-preprocess",
                ],
            ),
            patch.object(run_smiles, "SmilesConverter", ControlledConverter),
        ):
            run_smiles.main()
        self.assertEqual(batches[0][:3], ["Compound 1", "Compound 8", "Compound 1"])
        self.assertTrue(all(not label for label in batches[0][3:]))
        artifact = json.loads(output.read_text())
        self.assertEqual(
            [row["cpd_id"] for row in smiles_records(artifact)],
            ["Compound 1", "Compound 8"],
        )
        self.assertEqual(artifact["source_records"], [])

    def test_old_schema_observations_are_not_promoted_to_current_source_chemistry(self):
        _, _, artifact = self.prepare()
        artifact["schema"]["version"] = 1
        (self.run / ARTIFACTS["smiles"][0]).write_text(json.dumps(artifact))
        self.service.refresh(self.project.id)
        no_activity = self.service.results(self.project.id).items[1]
        self.assertIsNone(no_activity.smiles)
        self.assertEqual(no_activity.admet.properties, [])

    def test_pipeline_checks_complete_catalog_then_reuses_identical_checkpoint(self):
        path, payload, artifact = self.prepare()
        write_json_atomic(path, payload)
        artifact = complete_observation_artifact(
            payload,
            pdf=self.pdf,
            structures=self.run / "structures/metadata.json",
            binding_dir=path.parent,
        )
        output = self.root / "stage-output"
        output.mkdir()
        progress = PipelineProgress()
        log = {"steps": {}, "main_chain": ["smiles"], "status": "running"}
        progress.bind(str(output), log)
        state = PipelineContext(
            args=Namespace(pdf=str(self.pdf), gpu_mode="off"),
            progress=progress,
            base_dir=str(output),
            pipeline_log=log,
            active_cpds=["Compound 1"],
            n_bound=len(recognition_inputs(payload).formal),
            bind_json=str(path),
            bind_payload=payload,
            structures_json=str(self.run / "structures/metadata.json"),
            step_dirs={"smiles": str(output)},
        )

        def produce(*args, **kwargs):
            write_json_atomic(state.smiles_json, artifact)
            return CompletedProcess(
                [], 0, stdout="controlled same-QC catalog batch", stderr=""
            )

        with (
            patch(
                "patent_sar_extractor.application.stage_smiles.DECIMEREngine.runtime_identity",
                return_value={"fingerprint": "a" * 64},
            ),
            patch(
                "patent_sar_extractor.application.stage_smiles.run_in_env",
                side_effect=produce,
            ) as worker,
            patch(
                "patent_sar_extractor.application.stage_smiles.recognition_timeout",
                wraps=recognition_timeout,
            ) as budget,
        ):
            execute_smiles(state)
            total = 3 + len(artifact["candidate_records"])
            self.assertEqual(log["steps"]["smiles"]["total"], total)
            self.assertEqual(log["steps"]["smiles"]["reprint_total"], 1)
            self.assertEqual(log["steps"]["smiles"]["source_total"], 0)
            self.assertEqual(log["steps"]["smiles"]["formal_total"], 2)
            execute_smiles(state)
            worker.assert_called_once()
            budget.assert_called_once_with(total, state.started_monotonic)
            self.assertTrue(log["steps"]["smiles"]["from_cache"])

    def test_smiles_worker_cannot_omit_no_activity_catalog_results(self):
        path, payload, artifact = self.prepare()
        write_json_atomic(path, payload)
        artifact = complete_observation_artifact(
            payload,
            pdf=self.pdf,
            structures=self.run / "structures/metadata.json",
            binding_dir=path.parent,
        )
        artifact["records"] = [
            record for record in artifact["records"] if record["cpd_id"] != "Compound 8"
        ]
        self.assertFalse(
            smiles_artifact_is_current(artifact, require_all_candidates=True)
        )
        output = self.root / "stage-output"
        output.mkdir()
        progress = PipelineProgress()
        log = {"steps": {}, "main_chain": ["smiles"], "status": "running"}
        progress.bind(str(output), log)
        state = PipelineContext(
            args=Namespace(pdf=str(self.pdf), gpu_mode="off"),
            progress=progress,
            base_dir=str(output),
            pipeline_log=log,
            active_cpds=["Compound 1"],
            n_bound=len(recognition_inputs(payload).formal),
            bind_json=str(path),
            bind_payload=payload,
            structures_json=str(self.run / "structures/metadata.json"),
            step_dirs={"smiles": str(output)},
        )

        def produce(*args, **kwargs):
            write_json_atomic(state.smiles_json, artifact)
            return CompletedProcess(
                [], 0, stdout="controlled missing coverage", stderr=""
            )

        with (
            patch(
                "patent_sar_extractor.application.stage_smiles.DECIMEREngine.runtime_identity",
                return_value={"fingerprint": "a" * 64},
            ),
            patch(
                "patent_sar_extractor.application.stage_smiles.run_in_env",
                side_effect=produce,
            ),
            self.assertRaisesRegex(RuntimeError, "incompatible"),
        ):
            execute_smiles(state)
        self.assertFalse(Path(state.smiles_json + ".manifest.json").exists())
