"""Epoch-only guards do not rewrite original chemistry or manual audit identity."""

from __future__ import annotations

import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import test_job_attempts as attempt_cases
import test_source_stereochemistry as stereo_cases
from test_prediction_support import PredictionFixture
from test_web_support import WebFixture, artifact_run

from patent_sar_extractor import contracts as core
from patent_sar_extractor.application.stage_cache import (
    _step_fingerprint,
    _write_step_manifest,
)
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.ocsr import stereo_evidence, stereo_gate
from patent_sar_extractor.core.ocsr.smiles_cache import SmilesCache
from patent_sar_extractor.web.acceptance import authority, current
from patent_sar_extractor.web.analysis import AnalysisService
from patent_sar_extractor.web.artifacts import ArtifactView
from patent_sar_extractor.web.attempts import ARTIFACTS
from patent_sar_extractor.web.completion_inputs import completion_inputs
from patent_sar_extractor.web.correction_models import CorrectionRequest, EditableFields
from patent_sar_extractor.web.correction_storage import correction_source_fingerprint
from patent_sar_extractor.web.jobs import decode_spec
from patent_sar_extractor.web.models import JobRequest
from patent_sar_extractor.web.prediction_identity import compound_prediction_eligible
from patent_sar_extractor.web.processes import runtime_identity


class SourceEpochAuthorityTests(WebFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.next_epoch = core.STEREO_EVIDENCE_VERSION + 1

    def test_epoch_only_upgrade_cannot_reuse_old_qa_acceptance(self):
        root = artifact_run(self.root / "old-epoch", self.pdf, rows=1)
        view = ArtifactView.read(root)
        before = copy.deepcopy(view.payloads)
        with patch.object(core, "STEREO_EVIDENCE_VERSION", self.next_epoch):
            acceptance, historical = authority(
                view.payloads, pdf_verified=True, marker=None
            )
            self.assertEqual(acceptance.state, "historical")
            self.assertFalse(historical, "Upstream observations are still current")
            self.assertFalse(current(view.payloads["smiles"], "smiles"))
        self.assertEqual(view.payloads, before)

    def test_epoch_upgrade_retains_upstream_five_and_raw_not_derived_smiles(self):
        service, project, queue, job, spec = attempt_cases.AttemptTests.draft(self)
        attempt_cases.AttemptTests.classification(self, spec)
        root = Path(spec.output_dir)
        previous = ARTIFACTS["classify"][0]
        collections = {
            "locate": "selected_pages",
            "structures": "structures",
            "bind": "final_bindings",
            "activity": "rows",
        }
        for stage in core.CORE_STAGE_ORDER:
            if stage not in collections:
                continue
            relative, schema, version = ARTIFACTS[stage]
            payload = {
                **core.artifact_identity(schema, version),
                collections[stage]: [0] if stage == "locate" else [],
            }
            if stage == "bind":
                payload["execution_mode"] = "production_structure_led"
            write_json_atomic(root / relative, payload)
            _write_step_manifest(
                str(root / relative),
                _step_fingerprint(
                    stage, pdf_path=spec.pdf_path, dependencies=[str(root / previous)]
                ),
            )
            if stage == "locate":
                write_json_atomic(root / "structure_pages/crop_regions.json", {})
            previous = relative
        relative, schema, version = ARTIFACTS["smiles"]
        write_json_atomic(
            root / relative,
            {
                **core.artifact_identity(schema, version),
                "execution_mode": "production_decimer",
                "records": [
                    {"stereochemistry": {"version": core.STEREO_EVIDENCE_VERSION}}
                ],
            },
        )
        _write_step_manifest(
            str(root / relative),
            _step_fingerprint(
                "smiles",
                pdf_path=spec.pdf_path,
                dependencies=[str(root / previous)],
                params={"stereo_evidence_version": core.STEREO_EVIDENCE_VERSION},
            ),
        )
        cache = SmilesCache(str(root / "smiles/smiles_cache.sqlite"))
        engine = "decimer:raw-v2:" + "a" * 64
        for key, flag in (("b" * 64, "ok"), ("c" * 64, "stereo_source_conflict")):
            cache.save_result(
                key,
                engine,
                {
                    "status": "success",
                    "raw_smiles": "C[C@H](O)F",
                    "model_fingerprint": "a" * 64,
                    "quality_flag": flag,
                },
            )
        write_json_atomic(root / "final_qa_report.json", {"ok": True})
        attempt_cases.AttemptTests.summary(
            self,
            spec,
            status="complete",
            steps={name: {"status": "ok"} for name in ARTIFACTS},
        )
        attempt_cases.AttemptTests.finish(self, service, queue, job)
        before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        identity = runtime_identity()
        with patch.object(core, "STEREO_EVIDENCE_VERSION", self.next_epoch):
            self.assertEqual(runtime_identity(), identity)
            new_job = queue.enqueue(project.id, JobRequest())
        target = Path(decode_spec(service.store.job(new_job.id)["spec"]).output_dir)
        for stage in ("classify", "locate", "structures", "bind", "activity"):
            self.assertTrue((target / ARTIFACTS[stage][0]).is_file(), stage)
        self.assertFalse((target / relative).exists())
        self.assertFalse((target / "final_qa_report.json").exists())
        self.assertFalse((target / "pipeline_summary.json").exists())
        with (
            sqlite3.connect(root / "smiles/smiles_cache.sqlite") as source,
            sqlite3.connect(target / "smiles/smiles_cache.sqlite") as copied,
        ):
            self.assertEqual(
                source.execute(
                    "SELECT * FROM smiles_observations ORDER BY image_hash"
                ).fetchall(),
                copied.execute(
                    "SELECT * FROM smiles_observations ORDER BY image_hash"
                ).fetchall(),
            )
        self.assertEqual({p: p.read_bytes() for p in before}, before)


class SourceEpochProjectionTests(PredictionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.next_epoch = core.STEREO_EVIDENCE_VERSION + 1

    def test_derived_research_response_key_changes_on_epoch_without_code_change(self):
        analysis = AnalysisService(self.state, self.service)
        self.addCleanup(analysis.close)
        response = {
            "compound_id": "Compound 1",
            "status": "recognized",
            "smiles": "CCO",
            "engine": {"name": "DECIMER", "version": "2.8.0"},
            "review_only": True,
            "warnings": [],
        }
        with (
            patch.object(analysis, "_operation", return_value=nullcontext()),
            patch(
                "patent_sar_extractor.web.analysis.executable",
                return_value=Path(sys.executable),
            ),
            patch(
                "patent_sar_extractor.web.analysis.interpreter_key",
                return_value="controlled",
            ),
            patch(
                "patent_sar_extractor.web.analysis.decimer_model_key",
                return_value="controlled",
            ),
            patch.object(analysis, "_adapter_key", return_value="controlled"),
            patch.object(analysis.cache, "get", return_value=response) as get,
            patch.object(
                analysis, "_worker", side_effect=AssertionError("No model may run")
            ),
        ):
            analysis.recognize(self.project.id, "Compound 1")
            first = get.call_args.args
            with patch.object(core, "STEREO_EVIDENCE_VERSION", self.next_epoch):
                analysis.recognize(self.project.id, "Compound 1")
            self.assertNotEqual(first, get.call_args.args)

    def test_epoch_only_currentness_refresh_preserves_manual_graph_and_audit(self):
        document = self.service.get_correction(self.project.id, "Compound 1")
        fields = EditableFields(**{**document.values.model_dump(), "smiles": "CCN"})
        self.service.put_correction(
            self.project.id,
            "Compound 1",
            CorrectionRequest(
                expected_revision=0,
                expected_source_fingerprint=document.source_fingerprint,
                fields=fields,
            ),
        )
        project = self.service.store.project(self.project.id)
        raw = self.service.store.compound(self.project.id, "Compound 1")
        basis = correction_source_fingerprint(project, raw)
        with self.service.store.connect() as connection:
            audit = [
                tuple(row)
                for row in connection.execute("SELECT * FROM correction_audit")
            ]
            saved = [
                tuple(row) for row in connection.execute("SELECT * FROM corrections")
            ]
        source = {p: p.read_bytes() for p in self.run.rglob("*") if p.is_file()}
        with (
            patch.object(core, "STEREO_EVIDENCE_VERSION", self.next_epoch),
            patch.object(
                self.service,
                "refresh",
                side_effect=AssertionError(
                    "Do not replace raw rows for an epoch-only read"
                ),
            ),
        ):
            result = self.service.project(self.project.id)
            self.assertEqual(result.acceptance.state, "historical")
            item = self.service.effective_compound(self.project.id, "Compound 1")
            self.assertEqual(item.smiles, "CCN")
            self.assertFalse(item.correction.stale)
            self.assertTrue(compound_prediction_eligible(item))
            again = self.service.project(self.project.id)
            self.assertEqual(again.acceptance.state, "historical")
        after = self.service.store.project(self.project.id)
        self.assertEqual(correction_source_fingerprint(after, raw), basis)
        self.assertEqual(
            self.service.store.compound(self.project.id, "Compound 1"), raw
        )
        with self.service.store.connect() as connection:
            self.assertEqual(
                [
                    tuple(row)
                    for row in connection.execute("SELECT * FROM correction_audit")
                ],
                audit,
            )
            self.assertEqual(
                [tuple(row) for row in connection.execute("SELECT * FROM corrections")],
                saved,
            )
        self.assertEqual({p: p.read_bytes() for p in source}, source)
        self.assertEqual(
            json.loads(after["snapshot"])["source_stereo_epoch"], self.next_epoch
        )

    def test_epoch_only_read_preserves_explicit_manual_blank(self):
        document = self.service.get_correction(self.project.id, "Compound 1")
        self.service.put_correction(
            self.project.id,
            "Compound 1",
            CorrectionRequest(
                expected_revision=0,
                expected_source_fingerprint=document.source_fingerprint,
                fields=EditableFields(
                    **{**document.values.model_dump(), "smiles": None}
                ),
            ),
        )
        with patch.object(core, "STEREO_EVIDENCE_VERSION", self.next_epoch):
            item = self.service.effective_compound(self.project.id, "Compound 1")
            self.assertIsNone(item.smiles)
            self.assertFalse(item.correction.stale)
            self.assertFalse(compound_prediction_eligible(item))

    def test_stale_valid_and_rejected_originals_are_not_research_eligible(self):
        item = self.service.effective_compound(self.project.id, "Compound 1")
        before = copy.deepcopy(item.model_dump())
        with patch.object(core, "STEREO_EVIDENCE_VERSION", self.next_epoch):
            self.assertFalse(compound_prediction_eligible(item))
            project = self.service.store.project(self.project.id)
            raw = self.service.result_rows(self.project.id)
            by_id = {row["id"]: row for row in raw}
            for status in ("valid", "invalid"):
                candidate = item.model_copy(deep=True)
                candidate.recognition.status = status
                inputs = completion_inputs(project, by_id, [candidate])
                self.assertEqual([value[0] for value in inputs], [item.id])
        self.assertEqual(item.model_dump(), before)

    def test_current_epoch_invalid_observation_does_not_auto_retry(self):
        item = self.service.effective_compound(self.project.id, "Compound 1")
        item.recognition.status = "invalid"
        project = self.service.store.project(self.project.id)
        rows = {row["id"]: row for row in self.service.result_rows(self.project.id)}
        self.assertEqual(completion_inputs(project, rows, [item]), [])

    def test_epoch_publication_refuses_a_concurrently_changed_source(self):
        project = self.service.store.project(self.project.id)
        snapshot = json.loads(project["snapshot"])
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE projects SET snapshot=? WHERE id=?",
                (json.dumps({**snapshot, "concurrent": True}), self.project.id),
            )
        from patent_sar_extractor.web.errors import WebError

        with (
            patch.object(core, "STEREO_EVIDENCE_VERSION", self.next_epoch),
            self.assertRaises(WebError) as error,
        ):
            self.service._refresh_source_epoch(project, snapshot)
        self.assertEqual(error.exception.code, "projection_changed")
        self.assertTrue(
            json.loads(self.service.store.project(self.project.id)["snapshot"])[
                "concurrent"
            ]
        )


class SourceEpochRawRecertificationTests(unittest.TestCase):
    def test_raw_v2_cache_is_rescreened_after_epoch_change_without_model_or_mutation(
        self,
    ):
        next_epoch = core.STEREO_EVIDENCE_VERSION + 1
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "wave.png"
            stereo_cases.wave_image(image)
            raw = "C[C@H](O)C(=O)O"
            converter, calls = stereo_cases.SourceStereochemistryTests.converter(
                self, raw, cache=str(root / "raw.sqlite")
            )
            self.addCleanup(converter.close)
            first = converter.convert_one(
                {"cpd": "controlled", "image_path": str(image)}
            )
            with sqlite3.connect(root / "raw.sqlite") as connection:
                before = connection.execute(
                    "SELECT * FROM smiles_observations"
                ).fetchall()
            with (
                patch.object(core, "STEREO_EVIDENCE_VERSION", next_epoch),
                patch.object(stereo_evidence, "STEREO_EVIDENCE_VERSION", next_epoch),
                patch.object(stereo_gate, "STEREO_EVIDENCE_VERSION", next_epoch),
            ):
                self.assertIsNotNone(stereo_gate.stereo_record_error(first))
                second = converter.convert_one(
                    {"cpd": "controlled", "image_path": str(image)}
                )
                self.assertEqual(second["stereochemistry"]["version"], next_epoch)
                self.assertEqual(second["OCSR_quality_flag"], "stereo_source_conflict")
            self.assertEqual(calls, [str(image)])
            self.assertEqual(first["raw_smiles"], second["raw_smiles"])
            self.assertEqual(second["raw_smiles"], raw)
            self.assertTrue(second["engine_attempts"][0]["from_cache"])
            with sqlite3.connect(root / "raw.sqlite") as connection:
                self.assertEqual(
                    connection.execute("SELECT * FROM smiles_observations").fetchall(),
                    before,
                )


if __name__ == "__main__":
    unittest.main()
