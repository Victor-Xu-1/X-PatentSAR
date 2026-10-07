"""Focused real SQLite/worker/API contracts with explicit synthetic chemistry."""

from __future__ import annotations

import csv
import io
import json
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from test_prediction_fields import controlled_prediction
from test_prediction_support import PredictionFixture

from patent_sar_extractor.web.admet_history import read_admet_stage, write_admet_stage
from patent_sar_extractor.web.analysis_models import ADMETResponse, Property
from patent_sar_extractor.web.correction_models import CorrectionRequest
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.exports import export_csv, export_json
from patent_sar_extractor.web.jobs import JobQueue, decode_spec
from patent_sar_extractor.web.lead_endpoints import LEAD_ENDPOINTS
from patent_sar_extractor.web.models import Stage, StageProgress
from patent_sar_extractor.web.prediction_worker import run_lead_phase, run_predictions
from patent_sar_extractor.web.processes import CLIProcessRunner
from patent_sar_extractor.web.service import WorkspaceService
from patent_sar_extractor.web.storage import now
from patent_sar_extractor.workers.analysis_protocol import ADMET_BUNDLE_SHA256


class ControlledLeadAnalysis:
    """Does not infer patent molecules: tests the production-owned orchestration."""

    def __init__(self):
        self.calls = 0
        self.in_session = False

    @contextmanager
    def prediction_session(self, cancel=None):
        self.in_session = True
        try:
            yield
        finally:
            self.in_session = False

    def admet(self, smiles, *, cancel=None):
        self.calls += 1
        prediction = controlled_prediction()
        prediction.properties.extend(
            Property(
                key=key,
                label=key,
                value=0.8 if direction == "higher" else 0.1,
                unit="probability [0,1]",
                kind="prediction",
            )
            for key, direction in LEAD_ENDPOINTS.items()
        )
        return ADMETResponse(
            predictions=[
                prediction.model_copy(update={"smiles": value}) for value in smiles
            ],
            engine={
                "name": "ADMET-AI",
                "version": "2.0.1",
                "model_sha256": ADMET_BUNDLE_SHA256,
            },
            generated_at=now(),
            warnings=["Synthetic transport observation, not measured safety."],
        )


class LeadWorkflowTests(PredictionFixture, unittest.TestCase):
    def test_lead_tail_keeps_full_measured_research_duration(self):
        row, root, _ = self.draft()
        write_admet_stage(
            root,
            row,
            Stage(
                name="admet",
                status="ok",
                count=1,
                duration_seconds=3.0,
                progress=StageProgress(
                    completed=1,
                    total=1,
                    cache_hits=0,
                    failures=0,
                    device="cpu",
                    peak_rss_mb=None,
                ),
            ),
            core_completed=False,
        )
        run_lead_phase(self.service, row, root, False, None)
        actual, _ = read_admet_stage(row, root)
        self.assertEqual(actual.progress.phase, "lead")
        self.assertGreaterEqual(actual.duration_seconds, 3.0)

    def execute(self):
        row, root, _ = self.draft()
        write_admet_stage(root, row, Stage(name="admet"), core_completed=False)
        analysis = ControlledLeadAnalysis()
        from patent_sar_extractor.web.lead_scoring import prioritize_leads

        def after_release(*args, **kwargs):
            self.assertFalse(
                analysis.in_session, "Lead cannot compete with the model window"
            )
            return prioritize_leads(*args, **kwargs)

        with patch(
            "patent_sar_extractor.web.lead_scoring.prioritize_leads",
            side_effect=after_release,
        ):
            run_predictions(self.service, analysis, row)
        queue = JobQueue(self.service, CLIProcessRunner(), 10)
        queue._confirm_predictions(row["id"], decode_spec(row["spec"]))
        queue._finish(row["id"], "complete", None)
        return row, root, analysis

    def test_worker_tail_persists_candidate_restart_filters_and_research_exports(self):
        row, root, analysis = self.execute()
        self.assertEqual(analysis.calls, 1)
        self.assertEqual(read_admet_stage(row, root)[0].progress.phase, "lead")
        service = WorkspaceService(self.state)
        result = service.results(self.project.id).items[0]
        self.assertEqual((result.lead.status, result.lead.rank), ("selected", 1))
        self.assertEqual(len(result.admet.endpoints), 11)
        self.assertEqual(
            service.results(self.project.id, q="Compound 1").items[0].lead, result.lead
        )
        filters = json.dumps([{"column": "lead", "op": "not_empty"}])
        self.assertEqual(
            service.results(self.project.id, column_filters=filters).total, 1
        )
        values = service.filter_values(self.project.id, column="lead")
        self.assertEqual(values.items[0].value, "Lead 1")
        compounds = service.compounds(self.project.id)
        exported = json.loads(
            b"".join(export_json(service.project(self.project.id), compounds))
        )
        self.assertTrue(exported["review_only"])
        self.assertEqual(exported["items"][0]["lead"]["rank"], 1)
        record = next(
            csv.DictReader(
                io.StringIO(
                    b"".join(
                        export_csv(service.project(self.project.id), compounds)
                    ).decode("utf-8-sig")
                )
            )
        )
        self.assertEqual(record["Lead"], "Lead 1")
        self.assertEqual(service.project(self.project.id).acceptance.state, "accepted")

    def test_activity_edit_recomputes_without_model_and_preserves_raw_qa(self):
        self.execute()
        before = {path: path.read_bytes() for path in self.run.rglob("*.json")}
        document = self.service.corrections.get(self.project.id, "Compound 1")
        fields = document.values.model_copy(deep=True)
        fields.activities[0].value = 20.0
        with patch(
            "patent_sar_extractor.web.analysis.AnalysisService.admet",
            side_effect=AssertionError("Value edits must not run a model"),
        ):
            self.service.corrections.put(
                self.project.id,
                "Compound 1",
                CorrectionRequest(
                    expected_revision=document.revision,
                    expected_source_fingerprint=document.source_fingerprint,
                    fields=fields,
                ),
            )
        self.assertEqual(
            self.service.results(self.project.id).items[0].lead.status, "selected"
        )
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(
            self.service.lead_store.report(self.project.id)["job_id"], None
        )

    def test_manual_blank_properties_not_borrowed_and_candidate_withheld(self):
        self.execute()
        document = self.service.corrections.get(self.project.id, "Compound 1")
        fields = document.values.model_copy(deep=True)
        fields.property_overrides = {"Solubility_AqSolDB": None}
        fields.property_basis_smiles = fields.smiles
        self.service.corrections.put(
            self.project.id,
            "Compound 1",
            CorrectionRequest(
                expected_revision=document.revision,
                expected_source_fingerprint=document.source_fingerprint,
                fields=fields,
            ),
        )
        result = self.service.results(self.project.id).items[0]
        self.assertNotEqual(result.lead.status, "selected")
        self.assertIsNone(result.property_overrides["Solubility_AqSolDB"])

    def test_changed_inputs_publication_cas_and_read_staleness(self):
        self.execute()
        from patent_sar_extractor.web.lead_scoring import prioritize_leads

        def changing(*args, **kwargs):
            assessed = prioritize_leads(*args, **kwargs)
            with self.service.store.connect(write=True) as connection:
                connection.execute(
                    "INSERT INTO reviews VALUES(?,?,?,?,?,?)",
                    (
                        self.project.id,
                        "Compound 1",
                        "rejected",
                        "Controlled CAS change",
                        1,
                        now(),
                    ),
                )
            return assessed

        with (
            patch(
                "patent_sar_extractor.web.lead_scoring.prioritize_leads",
                side_effect=changing,
            ),
            self.assertRaises(WebError) as error,
        ):
            self.service.leads.refresh(self.project.id)
        self.assertEqual(error.exception.code, "lead_inputs_changed")
        self.assertEqual(
            self.service.results(self.project.id).items[0].lead.status, "stale"
        )

    def test_cancelled_owner_never_publishes_candidate(self):
        row, root, _ = self.draft()
        write_admet_stage(root, row, Stage(name="admet"), core_completed=False)
        event = threading.Event()
        event.set()
        with self.assertRaises(WebError):
            run_predictions(self.service, ControlledLeadAnalysis(), row, event)
        self.assertIsNone(self.service.lead_store.report(self.project.id))

    def test_task_completion_requires_current_complete_lead_report(self):
        row, _, _ = self.execute()
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "DELETE FROM lead_selections WHERE project_id=?", (self.project.id,)
            )
        queue = JobQueue(self.service, CLIProcessRunner(), 10)
        with self.assertRaises(WebError) as error:
            queue._confirm_predictions(row["id"], decode_spec(row["spec"]))
        self.assertEqual(error.exception.code, "lead_incomplete")

    def test_real_http_filters_export_and_paging_use_persisted_nomination(self):
        self.execute()
        with self.client() as client:
            path = f"/api/v1/projects/{self.project.id}"
            response = client.get(
                f"{path}/results",
                params={
                    "sort_column": "lead",
                    "column_filters": json.dumps(
                        [{"column": "lead", "op": "not_empty"}]
                    ),
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["items"][0]["lead"]["rank"], 1)
            choices = client.get(f"{path}/filter-values", params={"column": "lead"})
            self.assertEqual(choices.status_code, 200, choices.text)
            self.assertEqual(choices.json()["items"], [{"value": "Lead 1", "count": 1}])
            exported = client.post(f"{path}/export", json={"format": "json"})
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertEqual(exported.json()["items"][0]["lead"]["rank"], 1)

    def test_corrupt_cache_never_promotes_malformed_or_foreign_candidates(self):
        self.execute()
        with self.service.store.connect() as connection:
            original = connection.execute(
                "SELECT payload FROM lead_selections WHERE project_id=?",
                (self.project.id,),
            ).fetchone()[0]
        for mutation in ("schema", "project", "rank", "status", "extra"):
            with self.subTest(mutation=mutation):
                report = json.loads(original)
                if mutation == "schema":
                    report["schema"]["version"] = True
                elif mutation == "project":
                    report["project_id"] = "0" * 32
                elif mutation == "rank":
                    report["items"]["Compound 1"]["rank"] = 2
                elif mutation == "status":
                    report["status"], report["error_code"] = "failed", "lead_failed"
                else:
                    report["unexpected"] = True
                with self.service.store.connect(write=True) as connection:
                    connection.execute(
                        "UPDATE lead_selections SET payload=? WHERE project_id=?",
                        (json.dumps(report), self.project.id),
                    )
                with self.assertRaises(WebError) as error:
                    self.service.lead_store.report(self.project.id)
                self.assertEqual(error.exception.code, "lead_record_invalid")
                row = self.service.results(self.project.id).items[0]
                self.assertEqual(row.lead.status, "unranked")
                self.assertIn("lead_record_invalid", row.lead.warnings[0])
                self.assertEqual(row.smiles, "CCO")
