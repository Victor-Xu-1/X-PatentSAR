"""Saved/Web/export consumers cannot promote a disagreeing original depiction."""

from __future__ import annotations

import json
import shutil
import unittest

import test_corpus_predictions as corpus_tests
import test_uniform_recognition as uniform_tests
from test_prediction_support import PredictionFixture
from test_uniform_recognition import observation

from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.core.qa_inputs import load_qa_inputs
from patent_sar_extractor.smiles_artifact import build_smiles_artifact
from patent_sar_extractor.web.acceptance import ARTIFACTS
from patent_sar_extractor.web.completion_inputs import completion_inputs
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.prediction_worker import run_predictions
from patent_sar_extractor.workers.gen_final_results import export_validation


class ReprintProjectionTests(PredictionFixture, unittest.TestCase):
    def prepare(self):
        return uniform_tests.UniformRecognitionTests.prepare(self)

    def publish(self, artifact):
        (self.run / ARTIFACTS["smiles"][0]).write_text(json.dumps(artifact))
        self.service.refresh(self.project.id)

    def test_different_reprint_retains_one_row_and_blocks_properties(self):
        _, payload, artifact = self.prepare()
        source = recognition_inputs(payload).reprints[0]
        artifact["reprint_records"][0] = observation(source, "CCC")
        before = {
            path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()
        }
        self.publish(artifact)
        first, second = self.service.results(self.project.id).items
        self.assertEqual(first.id, "Compound 1")
        self.assertEqual(len(first.additional_sources), 1)
        self.assertEqual(first.recognition.status, "invalid")
        self.assertEqual(first.recognition.quality_flag, "source_reprint_review")
        self.assertIsNone(first.smiles)
        self.assertEqual(second.recognition.status, "valid")
        row, _ = corpus_tests.CorpusPredictionTests.job(self)
        model = corpus_tests.ControlledAnalysis()
        run_predictions(self.service, model, row)
        self.assertEqual(model.inputs, [["CCO"]])
        first = self.service.results(self.project.id).items[0]
        self.assertEqual(first.admet.status, "unavailable")
        self.assertEqual(first.admet.properties, [])
        for path, content in before.items():
            if path != self.run / ARTIFACTS["smiles"][0]:
                self.assertEqual(path.read_bytes(), content)

    def test_missing_reprint_is_review_not_an_extra_compound_or_a_clean_primary(self):
        _, _, artifact = self.prepare()
        artifact["reprint_records"] = []
        self.publish(artifact)
        items = self.service.results(self.project.id).items
        self.assertEqual([item.id for item in items], ["Compound 1", "Compound 8"])
        self.assertIsNone(items[0].smiles)
        self.assertEqual(items[0].recognition.status, "invalid")

    def test_no_current_reprint_field_cannot_keep_current_recognition(self):
        _, _, artifact = self.prepare()
        artifact.pop("reprint_records")
        self.publish(artifact)
        first = self.service.results(self.project.id).items[0]
        self.assertEqual(first.recognition.status, "unavailable")
        self.assertIsNone(first.smiles)

    def test_foreign_source_is_a_safe_contract_error(self):
        _, _, artifact = self.prepare()
        artifact["reprint_records"][0]["cpd_id"] = "Compound 81"
        with self.assertRaises(WebError) as rejected:
            self.publish(artifact)
        self.assertEqual(rejected.exception.code, "invalid_source_recognition")

    def test_changed_reprint_bytes_invalidate_chemistry_without_poll_inference(self):
        path, payload, artifact = self.prepare()
        alias = payload["compound_catalog"]["entries"][0]["additional_sources"][0]
        image = self.run / "separate-reprint.png"
        shutil.copyfile(alias["image_path"], image)
        alias["image_path"] = str(image)
        path.write_text(json.dumps(payload))
        metadata_path = self.run / ARTIFACTS["structures"][0]
        metadata = json.loads(metadata_path.read_text())
        for source in metadata["structures"]:
            if source["structure_id"] == alias["structure_id"]:
                source["image_path"] = str(image)
        metadata_path.write_text(json.dumps(metadata))
        artifact["reprint_records"][0] = observation(alias)
        self.publish(artifact)
        self.assertEqual(
            self.service.effective_compound(
                self.project.id, "Compound 1"
            ).recognition.status,
            "valid",
        )
        image.write_bytes(image.read_bytes() + b"changed original source")
        changed = self.service.effective_compound(self.project.id, "Compound 1")
        self.assertIsNone(changed.smiles)
        self.assertEqual(changed.recognition.quality_flag, "source_image_changed")

    def test_primary_only_completion_cannot_bypass_required_full_source_work(self):
        _, _, artifact = self.prepare()
        artifact.pop("reprint_records")
        self.publish(artifact)
        first = self.service.results(self.project.id).items[0]
        project = self.service.store.project(self.project.id)
        rows = {row["id"]: row for row in self.service.result_rows(self.project.id)}
        with self.assertRaises(WebError) as rejected:
            completion_inputs(project, rows, [first])
        self.assertEqual(rejected.exception.code, "source_reprints_require_extraction")

    def test_final_export_and_qa_withhold_only_the_disagreeing_owner(self):
        path, payload, artifact = self.prepare()
        plan = recognition_inputs(payload)
        payload["final_bindings"] = [*plan.formal, *plan.supplemental]
        path.write_text(json.dumps(payload))
        artifact = build_smiles_artifact(
            [observation(source) for source in payload["final_bindings"]],
            reprint_records=[observation(source, "CCC") for source in plan.reprints],
        )
        self.publish(artifact)
        bindings, records, errors = export_validation(
            str(path),
            str(self.run / ARTIFACTS["smiles"][0]),
            str(self.run / ARTIFACTS["activity"][0]),
            str(self.run / ARTIFACTS["classification"][0]),
        )
        self.assertEqual([source["cpd"] for source in bindings], ["Compound 8"])
        self.assertEqual([record["cpd_id"] for record in records], ["Compound 8"])
        self.assertTrue(any("depictions disagree" in reason for reason in errors))
        inputs = load_qa_inputs(str(self.run))
        self.assertEqual(inputs.valid_smiles_cpds, {"Compound 8"})
