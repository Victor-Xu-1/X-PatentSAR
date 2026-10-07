"""QA rejection messages reflect the real source-bound enrichment stage."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_corpus_predictions import ControlledAnalysis
from test_prediction_support import PredictionFixture
from test_web_support import artifact_run

from patent_sar_extractor import contracts
from patent_sar_extractor.web.acceptance import ARTIFACTS
from patent_sar_extractor.web.job_phases import PhaseResult
from patent_sar_extractor.web.jobs import JobQueue
from patent_sar_extractor.web.models import Error, JobRequest
from patent_sar_extractor.web.prediction_worker import run_predictions
from patent_sar_extractor.web.processes import SubprocessRunner
from patent_sar_extractor.web.storage import now


class RejectedEnrichmentTests(PredictionFixture, unittest.TestCase):
    def execute(self, mode):
        queue = JobQueue(self.service, SubprocessRunner(), 10)
        job = queue.enqueue(self.project.id, JobRequest(include_admet=True))
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='running',started_at=? WHERE id=?",
                (now(), job.id),
            )
        phases = []
        analysis = ControlledAnalysis() if mode == "qualified" else Mock()

        def phase(spec, deadline, **kwargs):
            phases.append("admet" if spec.admet_only else "extract")
            if not spec.admet_only:
                root = Path(spec.output_dir)
                generated = artifact_run(
                    root / "controlled-fixture", self.pdf, accepted=False, rows=1
                )
                for name in (
                    "activity",
                    "bindings",
                    "smiles",
                    "summary",
                    "classification",
                    "structures",
                    "qa",
                ):
                    path = generated / ARTIFACTS[name][0]
                    packet = json.loads(path.read_text())
                    if name == "summary":
                        packet.update(
                            status="failed_qa",
                            main_chain=list(contracts.CORE_STAGE_ORDER),
                            steps={
                                name: {"status": "ok"}
                                for name in contracts.CORE_STAGE_ORDER
                            },
                        )
                        packet["steps"]["qa"] = {
                            "status": "failed",
                            "strict_acceptance_ok": False,
                            "hard_errors": ["Controlled rejection"],
                        }
                    if mode != "qualified":
                        if name == "activity":
                            packet.update(rows=[], active_cpds=[])
                        elif name == "bindings":
                            packet.pop("compound_catalog", None)
                            packet["final_bindings"] = []
                        elif name == "smiles":
                            packet["records"] = []
                    destination = root / ARTIFACTS[name][0]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(json.dumps(packet))
                for path in generated.rglob("*ocr*.json"):
                    (root / path.relative_to(generated)).write_bytes(path.read_bytes())
                return PhaseResult(
                    "failed",
                    Error(code="extraction_failed", message="Controlled QA rejection"),
                    True,
                )
            if mode == "failure":
                return PhaseResult(
                    "failed",
                    Error(code="admet_failed", message="Controlled producer failure"),
                    True,
                )
            if mode != "missing":
                run_predictions(self.service, analysis, self.service.store.job(job.id))
            return PhaseResult("complete", None, True)

        with patch.object(queue.phases, "run", side_effect=phase):
            queue._execute(job.id)
        return self.service.job(job.id), phases, analysis

    def test_empty_enrichment_does_not_claim_research_values_or_promote_rejection(self):
        job, phases, analysis = self.execute("empty")
        self.assertEqual(phases, ["extract", "admet"])
        self.assertEqual((job.status, job.error.code), ("failed", "core_not_accepted"))
        self.assertIn("No qualified research values", job.error.message)
        self.assertNotIn("are available", job.error.message)
        self.assertEqual(
            (job.admet_stage.status, job.admet_stage.count, job.admet_stage.skipped),
            ("empty", 0, 1),
        )
        self.assertEqual(job.admet_stage.progress.total, 0)
        self.assertEqual(job.stages[-1].status, "failed")
        self.assertTrue(job.history_available)
        analysis.admet.assert_not_called()
        analysis.prediction_session.assert_not_called()
        result = self.service.results(self.project.id).items[0]
        self.assertEqual(result.admet.properties, [])
        self.assertEqual(
            self.service.project(self.project.id).acceptance.state, "failed"
        )
        with self.client() as client:
            response = client.get(f"/api/v1/jobs/{job.id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["admet_stage"]["status"], "empty")
            self.assertEqual(response.json()["error"]["message"], job.error.message)

    def test_actual_qualified_enrichment_retains_truthful_available_message(self):
        job, phases, analysis = self.execute("qualified")
        self.assertEqual(phases, ["extract", "admet"])
        self.assertEqual((job.status, job.error.code), ("failed", "core_not_accepted"))
        self.assertIn("Qualified research values are available", job.error.message)
        self.assertEqual((job.admet_stage.status, job.admet_stage.count), ("ok", 1))
        self.assertEqual(analysis.inputs, [["CCO"]])
        self.assertEqual(
            self.service.results(self.project.id).items[0].descriptors.status,
            "complete",
        )
        self.assertEqual(
            self.service.project(self.project.id).acceptance.state, "failed"
        )

    def test_missing_completed_evidence_is_still_rejected_as_incomplete(self):
        job, _, analysis = self.execute("missing")
        self.assertEqual((job.status, job.error.code), ("failed", "admet_incomplete"))
        self.assertNotIn("values are available", job.error.message)
        analysis.admet.assert_not_called()

    def test_failed_model_stage_is_not_relabelled_empty_or_research_complete(self):
        job, _, analysis = self.execute("failure")
        self.assertEqual((job.status, job.error.code), ("failed", "admet_failed"))
        self.assertEqual(job.admet_stage.status, "failed")
        self.assertNotIn("values are available", job.error.message)
        analysis.admet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
