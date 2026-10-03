"""Selected six-property research exports preserve values, provenance and original QA."""

import csv
import io
import json
import unittest

from test_prediction_support import PredictionFixture, controlled_summary

from patent_sar_extractor.web.exports import export_csv, export_json


class PredictionExportTests(PredictionFixture, unittest.TestCase):
    def test_six_fields_and_pinned_provenance_are_research_not_formal_qa(self):
        row, _, source = self.draft()
        self.service.predictions.put(
            self.project.id, "Compound 1", controlled_summary(source, "CCO", row["id"])
        )
        project = self.service.project(self.project.id)
        compounds = self.service.compounds(self.project.id)
        packet = json.loads(b"".join(export_json(project, compounds)))
        self.assertEqual(packet["acceptance"]["state"], "accepted")
        self.assertEqual(
            packet["formal_acceptance_scope"], "original_activity_association_only"
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
        self.assertEqual(record["admet_job_id"], row["id"])
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
