"""Actual owned phase carriers with controlled data, never scientific QA claims."""

from __future__ import annotations

import json
import threading
import time
import unittest

from test_prediction_support import ControlledPhaseRunner, PredictionFixture
from test_web_support import wait_job

from patent_sar_extractor.web.analysis_runtime import AnalysisSettings
from patent_sar_extractor.web.correction_storage import correction_source_fingerprint
from patent_sar_extractor.web.jobs import JobQueue
from patent_sar_extractor.web.models import JobRequest
from patent_sar_extractor.web.storage import now


class PredictionJobTests(PredictionFixture, unittest.TestCase):
    def test_normal_resume_inherits_original_admet_option_when_frontend_omits_it(self):
        from patent_sar_extractor.web.jobs import decode_spec

        queue = JobQueue(self.service, ControlledPhaseRunner(), 10)
        original = queue.enqueue(self.project.id, JobRequest(include_admet=True))
        queue._finish(original.id, "failed", None)
        self.assertTrue(self.service.job(original.id).can_resume)
        resumed = queue.enqueue(self.project.id, JobRequest(resume_job_id=original.id))
        self.assertTrue(resumed.include_admet)
        self.assertTrue(
            decode_spec(self.service.store.job(resumed.id)["spec"]).include_admet
        )

    def execute(self, *, mode="complete", accepted=True, admet_only=False):
        runner = ControlledPhaseRunner(mode=mode, accepted=accepted)
        queue = JobQueue(self.service, runner, 10)
        job = queue.enqueue(
            self.project.id, JobRequest(include_admet=True, admet_only=admet_only)
        )
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='running',started_at=? WHERE id=?",
                (now(), job.id),
            )
        queue._execute(job.id)
        return runner, queue, self.service.job(job.id)

    def test_core_cleanup_precedes_admet_and_source_remains_current_after_finish(self):
        runner, _, job = self.execute()
        self.assertEqual(runner.started_phases, ["extract", "admet"])
        self.assertEqual(runner._children, {})
        self.assertEqual(job.status, "complete", job.error)
        self.assertEqual(job.admet_stage.status, "ok")
        result = self.service.results(self.project.id).items[0]
        self.assertEqual(result.admet.status, "complete")
        project = self.service.store.project(self.project.id)
        raw = self.service.store.compound(self.project.id, result.id)
        self.assertEqual(
            result.admet.source_fingerprint, correction_source_fingerprint(project, raw)
        )
        self.assertEqual(
            self.service.project(self.project.id).acceptance.state, "accepted"
        )

    def test_core_qa_failure_never_starts_model_phase(self):
        runner, _, job = self.execute(accepted=False)
        self.assertEqual(runner.started_phases, ["extract"])
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error.code, "core_not_accepted")
        self.assertEqual(
            self.service.project(self.project.id).acceptance.state, "failed"
        )

    def test_completed_qa_rejection_keeps_failed_job_after_qualified_research(self):
        runner, _, job = self.execute(mode="qa_rejected", accepted=False)
        self.assertEqual(runner.started_phases, ["extract", "admet"])
        self.assertEqual(runner._children, {})
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error.code, "core_not_accepted")
        self.assertTrue(job.history_available)
        self.assertEqual(job.stages[-1].status, "failed")
        self.assertEqual(job.admet_stage.status, "ok")
        row = self.service.compounds(self.project.id)[0]
        self.assertEqual(row.admet.status, "complete")
        self.assertEqual(row.descriptors.status, "complete")
        self.assertEqual(
            self.service.project(self.project.id).acceptance.state, "failed"
        )

    def test_research_failure_preserves_formal_core_acceptance_and_stops_pending_rows(
        self,
    ):
        runner, _, job = self.execute(mode="failure")
        self.assertEqual(runner.started_phases, ["extract", "admet"])
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.admet_stage.status, "failed")
        self.assertTrue(job.history_available)
        self.assertEqual(
            self.service.project(self.project.id).acceptance.state, "accepted"
        )
        self.assertEqual(
            self.service.results(self.project.id).items[0].admet.status, "failed"
        )

    def test_admet_only_does_not_replace_projection_or_mutate_core_files(self):
        raw = self.service.store.compound(self.project.id, "Compound 1")
        before = self.service.store.project(self.project.id)
        artifacts = {p: p.read_bytes() for p in self.run.rglob("*.json")}
        runner, _, job = self.execute(admet_only=True)
        self.assertEqual(runner.started_phases, ["admet"])
        self.assertEqual(job.status, "complete", job.error)
        after = self.service.store.project(self.project.id)
        self.assertEqual(before["run_root"], after["run_root"])
        self.assertEqual(before["snapshot"], after["snapshot"])
        self.assertEqual(
            raw, self.service.store.compound(self.project.id, "Compound 1")
        )
        self.assertEqual(artifacts, {p: p.read_bytes() for p in artifacts})

    def test_cancel_active_prediction_cleans_carrier_and_terminal_rows(self):
        runner = ControlledPhaseRunner(mode="sleep")
        queue = JobQueue(self.service, runner, 10)
        job = queue.enqueue(
            self.project.id, JobRequest(include_admet=True, admet_only=True)
        )
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='running',started_at=? WHERE id=?",
                (now(), job.id),
            )
        thread = threading.Thread(target=queue._execute, args=(job.id,))
        thread.start()
        deadline = time.monotonic() + 4
        while (
            self.service.results(self.project.id).items[0].admet.status != "running"
            and time.monotonic() < deadline
        ):
            time.sleep(0.025)
        queue.cancel(job.id)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(runner._children, {})
        self.assertEqual(self.service.job(job.id).status, "cancelled")
        self.assertEqual(self.service.job(job.id).admet_stage.status, "failed")
        self.assertEqual(
            self.service.results(self.project.id).items[0].admet.status, "failed"
        )

    def test_real_api_default_correction_hook_enqueues_only_edited_structure(self):
        with self.client(
            runner=ControlledPhaseRunner(), analysis_settings=AnalysisSettings()
        ) as client:
            service = client.app.state.workspace
            endpoint = (
                f"/api/v1/projects/{self.project.id}/structures/Compound%201/correction"
            )
            document = client.get(endpoint).json()
            fields = {**document["values"], "smiles": "CCN"}
            response = client.put(
                endpoint,
                json={
                    "expected_revision": 0,
                    "expected_source_fingerprint": document["source_fingerprint"],
                    "fields": fields,
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            jobs = service.job_ids(self.project.id)
            self.assertEqual(len(jobs), 1)
            spec = json.loads(service.store.job(jobs[0])["spec"])
            self.assertTrue(spec["admet_only"])
            self.assertEqual(spec["admet_compounds"], ["Compound 1"])
            finished = wait_job(client, jobs[0], "complete")
            self.assertEqual(finished["admet_stage"]["status"], "ok")
            row = client.get(f"/api/v1/projects/{self.project.id}/results").json()[
                "items"
            ][0]
            self.assertEqual(row["smiles"], "CCN")
            self.assertEqual(row["admet"]["status"], "complete")
            self.assertEqual(
                service.get_correction(
                    self.project.id, "Compound 1"
                ).source_fingerprint,
                document["source_fingerprint"],
            )


if __name__ == "__main__":
    unittest.main()
