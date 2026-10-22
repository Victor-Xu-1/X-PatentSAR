"""Selected six-property research exports preserve values, provenance and original QA."""

import csv
import io
import json
import unittest

import test_web_results as source_controls
from test_prediction_support import controlled_summary
from test_web_support import WebFixture

from patent_sar_extractor.web.correction_storage import correction_source_fingerprint
from patent_sar_extractor.web.exports import export_csv, export_json
from patent_sar_extractor.web.prediction_jobs import enqueue_prediction
from patent_sar_extractor.web.service import WorkspaceService
from patent_sar_extractor.web.storage import now


class PredictionExportTests(WebFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.service = WorkspaceService(self.state)
        self.run, self.pdf = source_controls.ResultTests.complete_source_run(
            self, "property-source"
        )
        self.project = self.service.import_run(self.run, pdf_path=self.pdf)
        self.assertEqual(self.project.acceptance.state, "accepted")
        # This fixture isolates existing ADMET export transport, not descriptor
        # calculation. No model runs; original QA was actually generated above.
        self.service.result_queries.descriptors = None
        self.owner_id = self.service.results(self.project.id).items[0].id

    def test_six_fields_and_pinned_provenance_are_research_not_formal_qa(self):
        with self.service.store.connect(write=True) as connection:
            job_id = enqueue_prediction(
                self.service.store,
                connection,
                self.project.id,
                compound_ids=(self.owner_id,),
            )
            connection.execute(
                "UPDATE jobs SET status='running',started_at=? WHERE id=?",
                (now(), job_id),
            )
        source = correction_source_fingerprint(
            self.service.store.project(self.project.id),
            self.service.store.compound(self.project.id, self.owner_id),
        )
        self.service.predictions.put(
            self.project.id, self.owner_id, controlled_summary(source, "CCO", job_id)
        )
        project = self.service.project(self.project.id)
        compounds = self.service.compounds(self.project.id)
        packet = json.loads(b"".join(export_json(project, compounds)))
        self.assertEqual(packet["acceptance"]["state"], "accepted")
        self.assertEqual(
            packet["formal_acceptance_scope"],
            "proved_printed_identifier_structure_corpus",
        )
        self.assertTrue(packet["review_only"])
        self.assertEqual(packet["admet_observations"], 1)
        record = next(
            csv.DictReader(
                io.StringIO(
                    b"".join(export_csv(project, compounds)).decode("utf-8-sig")
                )
            )
        )
        self.assertEqual(record["admet_status"], "complete")
        self.assertEqual(record["LogP"], "-0.1")
        self.assertEqual(record["LogS_log_mol_L"], "-1.25")
        self.assertEqual(record["TPSA_A2"], "20.23")
        self.assertEqual(record["admet_source_fingerprint"], source)
        self.assertEqual(record["admet_job_id"], job_id)
        self.assertEqual(record["admet_review_only"], "True")
        self.assertEqual(record["review_only"], "True")

    def test_no_prediction_does_not_invent_values_or_downgrade_original_qa(self):
        project = self.service.project(self.project.id)
        compounds = self.service.compounds(self.project.id)
        packet = json.loads(b"".join(export_json(project, compounds)))
        self.assertFalse(packet["review_only"])
        record = next(
            csv.DictReader(
                io.StringIO(
                    b"".join(export_csv(project, compounds)).decode("utf-8-sig")
                )
            )
        )
        self.assertEqual(record["admet_status"], "not_run")
        self.assertEqual(record["MW_Dalton"], "")
        self.assertEqual(record["LogS_log_mol_L"], "")
