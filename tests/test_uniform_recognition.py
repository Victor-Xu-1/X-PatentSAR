"""Same source ownership/QC and metric path with or without measured activity."""

from __future__ import annotations

import hashlib
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
from test_prediction_support import PredictionFixture

from patent_sar_extractor.application.pipeline_context import PipelineContext
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.application.stage_cache import _bindings_ocsr_digest
from patent_sar_extractor.application.stage_smiles import execute_smiles
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.core.ocsr.smiles_qc import qc_smiles
from patent_sar_extractor.core.ocsr.stereo_evidence import (
    observe_stereo_symbols,
    source_checked_qc,
)
from patent_sar_extractor.smiles_artifact import build_smiles_artifact, smiles_records
from patent_sar_extractor.web.acceptance import ARTIFACTS
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.exports import export_json
from patent_sar_extractor.web.prediction_worker import run_predictions


def observation(binding, raw="CCO"):
    image = Path(binding["image_path"])
    checked = source_checked_qc(qc_smiles(raw), observe_stereo_symbols(image))
    return {
        **checked,
        "cpd_id": binding["cpd"],
        "structure_id": binding["structure_id"],
        "raw_smiles": raw,
        "image_hash": hashlib.sha256(image.read_bytes()).hexdigest(),
        "OCSR_quality_flag": checked["quality_flag"],
        "OCSR_status": "success"
        if checked["quality_flag"] == "ok"
        else "review_required",
        "model_fingerprint": "a" * 64,
    }


class UniformRecognitionTests(PredictionFixture, unittest.TestCase):
    def prepare(self, raw="CCO"):
        path, payload = catalog_tests.CompoundCatalogViewTests.catalog_run(self)
        formal, sources = recognition_inputs(payload)
        artifact = build_smiles_artifact(
            [observation(item) for item in formal],
            source_records=[observation(item, raw) for item in sources],
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
        artifact["source_records"][0] = {
            "cpd_id": "Compound 8",
            "structure_id": "numbered-without-activity",
            "OCSR_status": "image_missing",
            "OCSR_quality_flag": "empty_prediction",
            "rdkit_valid": False,
        }
        (self.run / ARTIFACTS["smiles"][0]).write_text(json.dumps(artifact))
        self.service.refresh(self.project.id)
        item = self.service.results(self.project.id).items[1]
        self.assertEqual(item.recognition.status, "unavailable")
        self.assertIsNone(item.smiles)

    def test_rejected_active_source_uses_the_same_no_prediction_standard(self):
        _, payload, artifact = self.prepare()
        artifact["records"][0] = observation(payload["final_bindings"][0], "CC*")
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
        artifact["source_records"][0]["structure_id"] = "S0"
        (self.run / ARTIFACTS["smiles"][0]).write_text(json.dumps(artifact))
        with self.assertRaises(WebError) as rejected:
            self.service.refresh(self.project.id)
        self.assertEqual(rejected.exception.code, "invalid_source_recognition")

    def test_catalog_union_preserves_formal_order_and_skips_reprint_inference(self):
        _, payload = catalog_tests.CompoundCatalogViewTests.catalog_run(self)
        formal, sources = recognition_inputs(payload)
        self.assertEqual([item["cpd"] for item in formal], ["Compound 1"])
        self.assertEqual([item["cpd"] for item in sources], ["Compound 8"])
        self.assertNotIn("proved-reprint", [item["structure_id"] for item in sources])
        payload["final_bindings"] = []
        self.assertEqual(
            [item["cpd"] for item in recognition_inputs(payload)[1]],
            ["Compound 1", "Compound 8"],
        )

    def test_conflicting_catalog_formal_owner_is_rejected_before_inference(self):
        _, payload = catalog_tests.CompoundCatalogViewTests.catalog_run(self)
        payload["final_bindings"][0]["structure_id"] = "wrong"
        with self.assertRaisesRegex(ValueError, "conflicts"):
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
        self.assertEqual(batches, [["Compound 1", "Compound 8"]])
        artifact = json.loads(output.read_text())
        self.assertEqual(
            [row["cpd_id"] for row in smiles_records(artifact)], ["Compound 1"]
        )
        self.assertEqual(
            [row["cpd_id"] for row in artifact["source_records"]], ["Compound 8"]
        )

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
        formal, supplemental = recognition_inputs(payload)
        payload["final_bindings"] = [*formal, *supplemental]
        write_json_atomic(path, payload)
        artifact = build_smiles_artifact(
            [observation(item) for item in payload["final_bindings"]]
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
            n_bound=len(recognition_inputs(payload)[0]),
            bind_json=str(path),
            bind_payload=payload,
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
        ):
            execute_smiles(state)
            self.assertEqual(log["steps"]["smiles"]["total"], 2)
            self.assertEqual(log["steps"]["smiles"]["source_total"], 0)
            self.assertEqual(log["steps"]["smiles"]["formal_total"], 2)
            execute_smiles(state)
            worker.assert_called_once()
            self.assertTrue(log["steps"]["smiles"]["from_cache"])

    def test_smiles_worker_cannot_omit_no_activity_catalog_results(self):
        path, payload, artifact = self.prepare()
        formal, supplemental = recognition_inputs(payload)
        payload["final_bindings"] = [*formal, *supplemental]
        write_json_atomic(path, payload)
        artifact = build_smiles_artifact(
            [observation(item) for item in payload["final_bindings"]]
        )
        artifact = build_smiles_artifact(
            [
                record
                for record in artifact["records"]
                if record["cpd_id"] != "Compound 8"
            ]
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
            n_bound=len(recognition_inputs(payload)[0]),
            bind_json=str(path),
            bind_payload=payload,
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
            self.assertRaisesRegex(RuntimeError, "omitted"),
        ):
            execute_smiles(state)
        self.assertFalse(Path(state.smiles_json + ".manifest.json").exists())
