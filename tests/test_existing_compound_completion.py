"""Existing proved sources must complete independently of measured activity."""

import json
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from test_compound_catalog_view import CompoundCatalogViewTests
from test_corpus_predictions import ControlledAnalysis, CorpusPredictionTests
from test_prediction_support import PredictionFixture
from test_uniform_recognition import observation

from patent_sar_extractor.web.admet_history import read_admet_stage
from patent_sar_extractor.web.correction_models import CorrectionRequest, EditableFields
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.exports import export_json
from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.prediction_worker import run_predictions
from patent_sar_extractor.web.processes import CLIProcessRunner
from patent_sar_extractor.web.service import WorkspaceService


class CompletionAnalysis(ControlledAnalysis):
    def _operation(self, cancel=None):
        return nullcontext()


class ControlledConverter:
    calls = []
    closed = False
    raw = "CCO"
    foreign = False
    failed = False

    def __init__(self, *args, **kwargs):
        pass

    def convert_one(self, binding, **kwargs):
        self.calls.append(binding["cpd"])
        result = observation(binding, self.raw)
        if self.foreign:
            result["cpd_id"] = "Compound 999"
        if self.failed:
            result["OCSR_status"] = "engine_timeout"
        return result

    def close(self):
        type(self).closed = True


class ExistingCompoundCompletionTests(PredictionFixture, unittest.TestCase):
    def catalog(self):
        CompoundCatalogViewTests.catalog_run(self)
        self.service.refresh(self.project.id)
        ControlledConverter.calls = []
        ControlledConverter.closed = False
        ControlledConverter.raw = "CCO"
        ControlledConverter.foreign = False
        ControlledConverter.failed = False

    def prepare(self):
        self.catalog()
        return CorpusPredictionTests.job(self)[0]

    def complete(self, row):
        analysis = CompletionAnalysis()
        with patch(
            "patent_sar_extractor.core.ocsr.smiles_converter.SmilesConverter",
            ControlledConverter,
        ):
            run_predictions(self.service, analysis, row)
        return analysis

    def test_existing_no_activity_gets_saved_smiles_properties_and_export(self):
        row = self.prepare()
        before = {p: p.read_bytes() for p in self.run.rglob("*") if p.is_file()}
        self.assertIsNone(
            self.service.effective_compound(self.project.id, "Compound 8").smiles
        )
        self.complete(row)
        item = self.service.effective_compound(self.project.id, "Compound 8")
        self.assertEqual(item.smiles, "CCO")
        self.assertEqual(item.activities, [])
        self.assertEqual(item.recognition.status, "valid")
        self.assertTrue(ControlledConverter.closed)
        self.service = WorkspaceService(self.state)
        self.assertEqual(
            self.service.get_correction(self.project.id, "Compound 8").values.smiles,
            "CCO",
        )
        result = self.service.results(self.project.id)
        saved = next(x for x in result.items if x.id == "Compound 8")
        self.assertEqual(saved.admet.status, "complete")
        self.assertEqual(len(saved.admet.properties), 6)
        exported = json.loads(
            b"".join(export_json(self.service.project(self.project.id), result.items))
        )
        self.assertEqual(
            next(x for x in exported["items"] if x["id"] == "Compound 8")["smiles"],
            "CCO",
        )
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_repeated_completion_reuses_current_saved_recognition_and_properties(self):
        row = self.prepare()
        self.complete(row)
        calls = list(ControlledConverter.calls)
        self.assertEqual(self.complete(row).inputs, [])
        self.assertEqual(ControlledConverter.calls, calls)

    def test_job_completion_withholds_success_until_numbered_sources_are_recognized(
        self,
    ):
        row = self.prepare()
        from test_prediction_support import controlled_stage, controlled_summary

        from patent_sar_extractor.web.admet_history import write_admet_stage
        from patent_sar_extractor.web.correction_storage import (
            correction_source_fingerprint,
        )

        project = self.service.store.project(self.project.id)
        raw = self.service.store.compound(self.project.id, "Compound 1")
        self.service.predictions.put(
            self.project.id,
            "Compound 1",
            controlled_summary(
                correction_source_fingerprint(project, raw), "CCO", row["id"]
            ),
        )
        spec = decode_spec(row["spec"])
        write_admet_stage(
            Path(spec.output_dir),
            row,
            controlled_stage().model_copy(update={"skipped": 1}),
            core_completed=False,
        )
        with self.assertRaises(WebError) as rejected:
            JobQueue(self.service, CLIProcessRunner(), 10)._confirm_predictions(
                row["id"], spec
            )
        self.assertEqual(rejected.exception.code, "admet_incomplete")

    def test_job_completion_accepts_actual_saved_recognition_and_properties(self):
        row = self.prepare()
        self.complete(row)
        JobQueue(self.service, CLIProcessRunner(), 10)._confirm_predictions(
            row["id"], decode_spec(row["spec"])
        )

    def test_non_graph_user_edit_survives_and_does_not_keep_smiles_blank(self):
        self.catalog()
        document = self.service.get_correction(self.project.id, "Compound 8")
        fields = EditableFields(
            **{**document.values.model_dump(), "display_id": "Operator name"}
        )
        self.service.put_correction(
            self.project.id,
            "Compound 8",
            CorrectionRequest(
                expected_revision=0,
                expected_source_fingerprint=document.source_fingerprint,
                fields=fields,
            ),
        )
        row = CorpusPredictionTests.job(self)[0]
        self.complete(row)
        value = self.service.effective_compound(self.project.id, "Compound 8")
        self.assertEqual((value.display_id, value.smiles), ("Operator name", "CCO"))
        after = self.service.get_correction(self.project.id, "Compound 8")
        self.assertEqual(after.values.smiles, "CCO")
        self.assertTrue(after.has_changes)
        self.assertEqual(after.revision, 1)

    def test_explicit_user_graph_is_never_auto_overwritten(self):
        self.catalog()
        document = self.service.get_correction(self.project.id, "Compound 8")
        fields = EditableFields(**{**document.values.model_dump(), "smiles": "CCO"})
        self.service.put_correction(
            self.project.id,
            "Compound 8",
            CorrectionRequest(
                expected_revision=0,
                expected_source_fingerprint=document.source_fingerprint,
                fields=fields,
            ),
        )
        row = CorpusPredictionTests.job(self)[0]
        self.complete(row)
        self.assertNotIn("Compound 8", ControlledConverter.calls)
        self.assertEqual(
            self.service.effective_compound(self.project.id, "Compound 8").smiles, "CCO"
        )

    def test_explicit_user_clear_after_completion_remains_blank(self):
        row = self.prepare()
        self.complete(row)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='complete' WHERE id=?", (row["id"],)
            )
        document = self.service.get_correction(self.project.id, "Compound 8")
        self.service.put_correction(
            self.project.id,
            "Compound 8",
            CorrectionRequest(
                expected_revision=document.revision,
                expected_source_fingerprint=document.source_fingerprint,
                fields=EditableFields(
                    **{**document.values.model_dump(), "smiles": None}
                ),
            ),
        )
        next_row = CorpusPredictionTests.job(self)[0]
        ControlledConverter.calls = []
        self.complete(next_row)
        self.assertNotIn("Compound 8", ControlledConverter.calls)
        value = self.service.results(self.project.id).items[1]
        self.assertIsNone(value.smiles)
        self.assertEqual(value.admet.properties, [])

    def test_form_opened_before_model_completion_cannot_accidentally_clear_new_graph(
        self,
    ):
        row = self.prepare()
        old = self.service.get_correction(self.project.id, "Compound 8")
        self.complete(row)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='complete' WHERE id=?", (row["id"],)
            )
        with self.assertRaises(WebError) as conflict:
            self.service.put_correction(
                self.project.id,
                "Compound 8",
                CorrectionRequest(
                    expected_revision=old.revision,
                    expected_source_fingerprint=old.source_fingerprint,
                    fields=old.values,
                ),
            )
        self.assertEqual(conflict.exception.code, "correction_source_conflict")
        current = self.service.get_correction(self.project.id, "Compound 8")
        self.assertNotEqual(old.source_fingerprint, current.source_fingerprint)
        self.assertEqual(current.values.smiles, "CCO")

    def test_foreign_observation_cannot_get_saved_or_predicted(self):
        row = self.prepare()
        ControlledConverter.foreign = True
        with self.assertRaises(WebError) as rejected:
            self.complete(row)
        self.assertEqual(rejected.exception.code, "recognition_owner")
        self.assertTrue(ControlledConverter.closed)
        self.assertIsNone(
            self.service.effective_compound(self.project.id, "Compound 8").smiles
        )
        stage, _ = read_admet_stage(row, Path(decode_spec(row["spec"]).output_dir))
        self.assertEqual(stage.status, "failed")
        self.assertEqual(stage.progress.phase, "recognition")

    def test_syntax_rejection_keeps_source_and_has_no_usable_properties(self):
        row = self.prepare()
        ControlledConverter.raw = "CC*"
        analysis = self.complete(row)
        self.assertEqual(analysis.inputs, [])
        result = self.service.results(self.project.id)
        self.assertTrue(all(x.recognition.status == "invalid" for x in result.items))
        self.assertTrue(
            all(x.smiles is None and not x.admet.properties for x in result.items)
        )

    def test_engine_failure_is_failed_stage_not_success_with_blank_data(self):
        row = self.prepare()
        ControlledConverter.failed = True
        with self.assertRaises(WebError) as rejected:
            self.complete(row)
        self.assertEqual(rejected.exception.code, "recognition_failed")
        self.assertTrue(ControlledConverter.closed)
        self.assertIsNone(
            self.service.effective_compound(self.project.id, "Compound 8").smiles
        )

    def test_cancel_before_first_image_does_not_save_or_infer(self):
        row = self.prepare()
        event = threading.Event()
        event.set()
        with (
            patch(
                "patent_sar_extractor.core.ocsr.smiles_converter.SmilesConverter",
                ControlledConverter,
            ),
            self.assertRaises(WebError),
        ):
            run_predictions(self.service, CompletionAnalysis(), row, event)
        self.assertEqual(ControlledConverter.calls, [])
        self.assertTrue(ControlledConverter.closed)

    def test_changed_source_crop_cannot_keep_old_smiles_or_properties(self):
        row = self.prepare()
        self.complete(row)
        crop = self.run / "crop.png"
        crop.write_bytes(crop.read_bytes() + b"changed source")
        result = self.service.results(self.project.id)
        self.assertTrue(
            all(x.smiles is None and not x.admet.properties for x in result.items)
        )
        self.assertTrue(
            all(
                x.recognition.quality_flag == "completion_source_changed"
                for x in result.items
            )
        )
