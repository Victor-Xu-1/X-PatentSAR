"""Unassociated sources remain visible; only actual valid SMILES enter ADMET."""

from __future__ import annotations

import json
import unittest
from contextlib import nullcontext

from test_prediction_fields import controlled_prediction
from test_prediction_support import PredictionFixture

from patent_sar_extractor.web.admet_history import read_admet_stage, write_admet_stage
from patent_sar_extractor.web.analysis_models import ADMETResponse
from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.models import Stage
from patent_sar_extractor.web.prediction_jobs import enqueue_prediction
from patent_sar_extractor.web.prediction_worker import run_predictions
from patent_sar_extractor.web.processes import CLIProcessRunner
from patent_sar_extractor.web.storage import now
from patent_sar_extractor.workers.analysis_protocol import ADMET_BUNDLE_SHA256


class ControlledAnalysis:
    def __init__(self):
        self.inputs = []

    def prediction_session(self, cancel=None):
        return nullcontext()

    def admet(self, smiles, *, cancel=None):
        self.inputs.append(smiles)
        return ADMETResponse(
            predictions=[controlled_prediction() for _ in smiles],
            engine={
                "name": "ADMET-AI",
                "version": "2.0.1",
                "model_sha256": ADMET_BUNDLE_SHA256,
            },
            generated_at=now(),
            warnings=["Controlled observation; not a scientific inference result."],
            review_only=True,
        )


class CorpusPredictionTests(PredictionFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        # These cases exercise anonymous/unproved source eligibility, not the
        # separate proved-ID recognition-completion producer.
        path = self.run / "structure_bindings/bindings.json"
        payload = json.loads(path.read_text())
        payload.pop("compound_catalog", None)
        path.write_text(json.dumps(payload))
        self.service.refresh(self.project.id)

    def job(self):
        with self.service.store.connect(write=True) as connection:
            job_id = enqueue_prediction(self.service.store, connection, self.project.id)
            connection.execute(
                "UPDATE jobs SET status='running',started_at=? WHERE id=?",
                (now(), job_id),
            )
        row = self.service.store.job(job_id)
        spec = decode_spec(row["spec"])
        from pathlib import Path

        write_admet_stage(
            Path(spec.output_dir), row, Stage(name="admet"), core_completed=False
        )
        return row, spec

    def test_missing_smiles_source_is_explicitly_skipped_without_losing_the_row(self):
        path = self.run / "structures/metadata.json"
        packet = json.loads(path.read_text())
        packet["structures"].append(
            {**packet["structures"][0], "structure_id": "source-only"}
        )
        path.write_text(json.dumps(packet))
        self.service.refresh(self.project.id)
        row, spec = self.job()
        analysis = ControlledAnalysis()
        run_predictions(self.service, analysis, row)
        self.assertEqual(analysis.inputs, [["CCO"]])
        from pathlib import Path

        stage, _ = read_admet_stage(row, Path(spec.output_dir))
        self.assertEqual(stage.status, "ok")
        self.assertEqual(stage.skipped, 1)
        self.assertEqual(stage.count, 1)
        self.assertEqual(stage.progress.total, 1)
        JobQueue(self.service, CLIProcessRunner(), 10)._confirm_predictions(
            row["id"], spec
        )
        result = self.service.results(self.project.id)
        self.assertEqual(result.total, 2)
        retained = next(
            value for value in result.items if value.record_kind == "structure_only"
        )
        self.assertEqual(retained.admet.status, "unavailable")
        self.assertEqual(retained.admet.properties, [])

    def test_all_unrecognized_sources_produce_empty_not_fake_model_success(self):
        from patent_sar_extractor.web.acceptance import ARTIFACTS

        for name, keys in (
            ("activity", ("rows", "active_cpds")),
            ("bindings", ("final_bindings",)),
            ("smiles", ("records",)),
        ):
            path = self.run / ARTIFACTS[name][0]
            packet = json.loads(path.read_text())
            for key in keys:
                packet[key] = []
            path.write_text(json.dumps(packet))
        self.service.refresh(self.project.id)
        row, spec = self.job()
        analysis = ControlledAnalysis()
        run_predictions(self.service, analysis, row)
        self.assertEqual(analysis.inputs, [])
        from pathlib import Path

        stage, _ = read_admet_stage(row, Path(spec.output_dir))
        self.assertEqual(stage.status, "empty")
        self.assertEqual(stage.skipped, 1)
        self.assertEqual(stage.count, 0)
        self.assertEqual(stage.progress.total, 0)
        JobQueue(self.service, CLIProcessRunner(), 10)._confirm_predictions(
            row["id"], spec
        )
        self.assertEqual(self.service.results(self.project.id).total, 1)
        self.assertEqual(
            self.service.results(self.project.id).items[0].admet.properties, []
        )
