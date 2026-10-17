"""Existing proved sources must complete independently of measured activity."""

import json
import threading
import unittest
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from test_compound_catalog_view import CompoundCatalogViewTests
from test_corpus_predictions import ControlledAnalysis, CorpusPredictionTests
from test_prediction_support import PredictionFixture
from test_uniform_recognition import observation

from patent_sar_extractor.core.ocsr import smiles_converter as converter_module
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.web.admet_history import read_admet_stage
from patent_sar_extractor.web.analysis_models import Property
from patent_sar_extractor.web.correction_models import CorrectionRequest, EditableFields
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.exports import export_json
from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.lead_endpoints import LEAD_ENDPOINTS
from patent_sar_extractor.web.prediction_worker import run_predictions
from patent_sar_extractor.web.processes import CLIProcessRunner
from patent_sar_extractor.web.service import WorkspaceService


class CompletionAnalysis(ControlledAnalysis):
    def _operation(self, cancel=None):
        return nullcontext()

    def admet(self, smiles, *, cancel=None):
        response = super().admet(smiles, cancel=cancel)
        # The production cache requires the full reviewed endpoint inventory.
        # These explicit controlled probabilities are test data, not predictions.
        for prediction in response.predictions:
            prediction.properties.extend(
                Property(
                    key=key,
                    label=key,
                    value=0.5,
                    unit="probability [0,1]",
                    kind="prediction",
                )
                for key in LEAD_ENDPOINTS
            )
        return response


class ControlledConverter:
    calls: ClassVar[list] = []
    source_calls: ClassVar[list] = []
    raw_by_source: ClassVar[dict] = {}
    failed_sources: ClassVar[set] = set()
    after_source: ClassVar[Callable | None] = None
    finalized_sources: ClassVar[list] = []
    closed = False
    raw = "CCO"
    foreign = False
    failed = False

    def __init__(self, *args, **kwargs):
        pass

    def convert_one(self, binding, **kwargs):
        self.calls.append(binding["cpd"])
        self.source_calls.append(binding["structure_id"])
        result = observation(
            binding, self.raw_by_source.get(binding["structure_id"], self.raw)
        )
        if self.foreign:
            result["cpd_id"] = "Compound 999"
        if self.failed or binding["structure_id"] in self.failed_sources:
            result["OCSR_status"] = "engine_timeout"
        if type(self).after_source is not None:
            type(self).after_source(binding)
        return result

    def close(self):
        type(self).closed = True

    def finalize_batch(self, records, **kwargs):
        type(self).finalized_sources = records
        self.close()
        return records


class ExistingCompoundCompletionTests(PredictionFixture, unittest.TestCase):
    def catalog(self):
        _, payload = CompoundCatalogViewTests.catalog_run(self)
        path = self.run / "smiles/smiles_results.json"
        artifact = json.loads(path.read_text())
        # These scenarios begin with an independently qualified active owner;
        # incomplete/different reprints have separate source-consistency controls.
        artifact["reprint_records"] = [
            observation(source) for source in recognition_inputs(payload).reprints
        ]
        path.write_text(json.dumps(artifact))
        self.service.refresh(self.project.id)
        ControlledConverter.calls = []
        ControlledConverter.source_calls = []
        ControlledConverter.raw_by_source = {}
        ControlledConverter.failed_sources = set()
        ControlledConverter.after_source = None
        ControlledConverter.finalized_sources = []
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

    def pending_reprints(self):
        self.catalog()
        path = self.run / "smiles/smiles_results.json"
        artifact = json.loads(path.read_text())
        artifact.pop("reprint_records")
        path.write_text(json.dumps(artifact))
        self.service.refresh(self.project.id)
        return CorpusPredictionTests.job(self)[0]

    def test_missing_reprints_complete_in_the_same_owned_job_and_source_cache(self):
        row = self.pending_reprints()
        before = {
            path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()
        }
        self.complete(row)
        self.assertEqual(
            ControlledConverter.source_calls,
            ["S0", "proved-reprint", "numbered-without-activity"],
        )
        first, second = self.service.results(self.project.id).items
        self.assertEqual(
            (first.recognition.status, second.recognition.status), ("valid", "valid")
        )
        self.assertEqual(len(ControlledConverter.finalized_sources), 3)
        self.assertTrue(
            all(
                "reprint_records" not in record
                for record in ControlledConverter.finalized_sources
            )
        )
        self.assertEqual((first.smiles, second.smiles), ("CCO", "CCO"))
        self.assertEqual(
            (first.admet.status, second.admet.status), ("complete", "complete")
        )
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        calls = list(ControlledConverter.source_calls)
        self.assertEqual(self.complete(row).inputs, [])
        self.assertEqual(ControlledConverter.source_calls, calls)

    def test_completed_reprint_disagreement_cannot_promote_a_primary_overlay(self):
        row = self.pending_reprints()
        ControlledConverter.raw_by_source = {"proved-reprint": "CCC"}
        analysis = self.complete(row)
        self.assertEqual(analysis.inputs, [["CCO"]])
        first, second = self.service.results(self.project.id).items
        self.assertEqual(first.recognition.status, "invalid")
        self.assertEqual(first.recognition.quality_flag, "source_reprint_review")
        self.assertIsNone(first.smiles)
        self.assertEqual(first.admet.properties, [])
        self.assertEqual(second.recognition.status, "valid")
        self.assertEqual(second.admet.status, "complete")

    def test_native_converter_preserves_every_source_and_reuses_only_raw_cache(self):
        row = self.pending_reprints()
        calls, closed = [], []

        class ObservedEngine:
            def __init__(self, **kwargs):
                pass

            def runtime_identity(self):
                return {"fingerprint": "a" * 64}

            def predict(self, image, timeout=60):
                calls.append(image)
                return {
                    "status": "success",
                    "raw_smiles": "CCO",
                    "model_fingerprint": "a" * 64,
                }

            def close(self):
                closed.append(True)

        with patch.dict(converter_module.ENGINE_MAP, {"decimer": ObservedEngine}):
            run_predictions(self.service, CompletionAnalysis(), row)
        # The generated source images have identical bytes, not identical IDs.
        # The real converter reuses inference, then rechecks each original frame.
        self.assertEqual(len(calls), 1)
        self.assertTrue(closed)
        self.service = WorkspaceService(self.state)
        first, second = self.service.results(self.project.id).items
        self.assertEqual((first.smiles, second.smiles), ("CCO", "CCO"))
        self.assertEqual(len(first.additional_sources), 1)
        with self.service.store.connect() as connection:
            saved = connection.execute(
                "SELECT observation FROM compound_recognitions "
                "WHERE project_id=? AND compound_id=?",
                (self.project.id, first.id),
            ).fetchone()
        record = json.loads(saved[0])
        self.assertEqual(record["structure_id"], "S0")
        self.assertEqual(record["reprint_records"][0]["structure_id"], "proved-reprint")
        self.assertEqual(record["reprint_records"][0]["cpd_id"], first.id)
        self.assertTrue(
            record["reprint_records"][0]["engine_attempts"][0]["from_cache"]
        )
        self.assertEqual(
            (first.admet.status, second.admet.status), ("complete", "complete")
        )

    def test_alias_timeout_keeps_raw_evidence_and_never_publishes_the_primary(self):
        row = self.pending_reprints()
        ControlledConverter.failed_sources = {"proved-reprint"}
        with self.assertRaises(WebError) as failed:
            self.complete(row)
        self.assertEqual(failed.exception.code, "recognition_failed")
        self.assertEqual(ControlledConverter.source_calls, ["S0", "proved-reprint"])
        self.assertTrue(ControlledConverter.closed)
        self.assertIsNone(
            self.service.effective_compound(self.project.id, "Compound 1").smiles
        )
        output = Path(decode_spec(row["spec"]).output_dir)
        snapshots = list((output / "recognition").glob("*.json"))
        self.assertEqual(len(snapshots), 1)
        saved = json.loads(snapshots[0].read_text())["observation"]
        self.assertEqual(saved["raw_smiles"], "CCO")
        self.assertEqual(saved["reprint_records"][0]["OCSR_status"], "engine_timeout")
        stage, _ = read_admet_stage(row, output)
        self.assertEqual(
            (stage.status, stage.progress.total, stage.progress.failures),
            ("failed", 3, 1),
        )

    def test_cancel_between_originals_keeps_partial_observations_without_publication(
        self,
    ):
        row = self.pending_reprints()
        event = threading.Event()
        ControlledConverter.after_source = lambda binding: event.set()
        with (
            patch(
                "patent_sar_extractor.core.ocsr.smiles_converter.SmilesConverter",
                ControlledConverter,
            ),
            self.assertRaises(WebError) as cancelled,
        ):
            run_predictions(self.service, CompletionAnalysis(), row, event)
        self.assertEqual(cancelled.exception.code, "recognition_cancelled")
        self.assertEqual(ControlledConverter.source_calls, ["S0"])
        self.assertTrue(ControlledConverter.closed)
        output = Path(decode_spec(row["spec"]).output_dir)
        saved = [
            json.loads(path.read_text())["observation"]
            for path in (output / "recognition").glob("*.json")
        ]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["raw_smiles"], "CCO")
        self.assertEqual(saved[0]["reprint_records"], [])
        stage, _ = read_admet_stage(row, output)
        self.assertEqual(
            (stage.progress.completed, stage.progress.total, stage.progress.failures),
            (1, 3, 0),
        )
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM compound_recognitions WHERE project_id=?",
                    (self.project.id,),
                ).fetchone()[0],
                0,
            )

    def test_source_byte_change_during_recognition_refuses_publication(self):
        row = self.pending_reprints()

        def change_after_read(binding):
            if binding["structure_id"] == "proved-reprint":
                path = Path(binding["image_path"])
                path.write_bytes(path.read_bytes() + b"changed after observation")

        ControlledConverter.after_source = change_after_read
        with self.assertRaises(WebError) as rejected:
            self.complete(row)
        self.assertEqual(rejected.exception.code, "recognition_source_changed")
        with self.service.store.connect() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM compound_recognitions WHERE project_id=?",
                    (self.project.id,),
                ).fetchone()[0],
                0,
            )
        output = Path(decode_spec(row["spec"]).output_dir)
        stage, _ = read_admet_stage(row, output)
        self.assertEqual(
            (stage.progress.completed, stage.progress.total, stage.progress.failures),
            (2, 3, 0),
        )

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
        # A rejected source cannot veto an independent already-qualified source.
        self.assertEqual(analysis.inputs, [["CCO"]])
        result = self.service.results(self.project.id)
        rejected = next(x for x in result.items if x.id == "Compound 8")
        self.assertEqual(rejected.recognition.status, "invalid")
        self.assertTrue(rejected.smiles is None and not rejected.admet.properties)

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
                x.recognition.quality_flag
                in {"completion_source_changed", "source_image_changed"}
                for x in result.items
            )
        )


def load_tests(loader, _tests, _pattern):
    # One explicit feature family, not imported unrelated TestCases or global
    # discovery. The observation-boundary regressions share the same fixture.
    from test_completion_observation_safety import CompletionObservationSafetyTests

    suite = unittest.TestSuite(
        loader.loadTestsFromTestCase(case)
        for case in (ExistingCompoundCompletionTests, CompletionObservationSafetyTests)
    )
    suite.addTests(
        loader.loadTestsFromName(
            "test_release_workflows.ReleaseWorkflowTests."
            "test_ci_version_check_precedes_dependencies_and_stays_read_only"
        )
    )
    # Only this cache class's six own cases; do not duplicate its inherited
    # completion scenarios or imported TestCases through module discovery.
    for method in (
        "test_import_does_not_write_compounds_audit_or_acceptance",
        "test_exact_key_conflict_cannot_overwrite_existing_raw_observation",
        "test_foreign_model_and_symlink_cache_are_rejected",
        "test_import_busy_guard_uses_same_workspace_lease",
        "test_per_original_cache_isolation_and_cli_contract",
        "test_auto_published_raw_cache_reuses_next_project_without_model_loading",
    ):
        suite.addTests(
            loader.loadTestsFromName(
                "test_shared_observations.SharedObservationTests." + method
            )
        )
    return suite
