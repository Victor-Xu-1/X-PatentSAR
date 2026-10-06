"""Current calculations survive model failure, with one property authority."""

import csv
import io
import json
import unittest

from test_prediction_support import PredictionFixture

from patent_sar_extractor.web.descriptor_fields import (
    compute_descriptors,
    descriptor_engine,
)
from patent_sar_extractor.web.descriptor_models import DescriptorSummary
from patent_sar_extractor.web.dto import Error
from patent_sar_extractor.web.exports import export_csv
from patent_sar_extractor.web.prediction_models import PredictionSummary
from patent_sar_extractor.web.prediction_storage import smiles_digest
from patent_sar_extractor.web.property_values import effective_property_values
from patent_sar_extractor.web.storage import now


class DescriptorStorageTests(PredictionFixture, unittest.TestCase):
    def publish(self):
        job, _, source = self.draft()
        summary = DescriptorSummary(
            status="complete",
            properties=compute_descriptors("CCO"),
            source_fingerprint=source,
            smiles_sha256=smiles_digest("CCO"),
            engine=descriptor_engine(),
            generated_at=now(),
            job_id=job["id"],
        )
        self.service.descriptors.put(self.project.id, "Compound 1", summary)
        self.service.predictions.put(
            self.project.id,
            "Compound 1",
            PredictionSummary(
                status="failed",
                source_fingerprint=source,
                smiles_sha256=smiles_digest("CCO"),
                job_id=job["id"],
                error=Error(
                    code="controlled_logS_failure", message="Controlled model failure."
                ),
            ),
        )
        return job, source, summary

    def test_five_values_table_filter_csv_survive_absent_model(self):
        job, source, _summary = self.publish()
        row = self.service.compounds(self.project.id)[0]
        self.assertEqual(row.descriptors.status, "complete")
        self.assertEqual(row.admet.status, "failed")
        values = effective_property_values(row)
        self.assertAlmostEqual(values["molecular_weight"], 46.069)
        self.assertIsNone(values["Solubility_AqSolDB"])
        record = next(
            csv.DictReader(
                io.StringIO(
                    b"".join(
                        export_csv(self.service.project(self.project.id), [row])
                    ).decode("utf-8-sig")
                )
            )
        )
        self.assertEqual(record["MW_Dalton"], str(values["molecular_weight"]))
        self.assertEqual(record["LogS_log_mol_L"], "")
        self.assertEqual(record["descriptor_job_id"], job["id"])
        self.assertEqual(record["descriptor_source_fingerprint"], source)
        choices = self.service.result_queries.filter_values(
            self.project.id, column="property:molecular_weight"
        )
        self.assertTrue(choices.items)

    def test_explicit_manual_null_wins_over_both_producers(self):
        self.publish()
        row = self.service.compounds(self.project.id)[0]
        row.property_overrides = {"molecular_weight": None, "logP": 0}
        values = effective_property_values(row)
        self.assertIsNone(values["molecular_weight"])
        self.assertEqual(values["logP"], 0)
        self.assertIsNotNone(values["tpsa"])

    def test_stale_graph_and_corrupt_engine_never_expose_values(self):
        _, source, _ = self.publish()
        current = self.service.descriptors.summaries(
            self.project.id, [("Compound 1", source, "CCN")]
        )["Compound 1"]
        self.assertEqual(current.status, "stale")
        self.assertEqual(current.properties, [])
        with self.service.store.connect(write=True) as connection:
            saved = json.loads(
                connection.execute(
                    "SELECT payload FROM molecular_descriptors"
                ).fetchone()[0]
            )
            saved["observation"]["engine"]["algorithm_sha256"] = "0" * 64
            connection.execute(
                "UPDATE molecular_descriptors SET payload=?", (json.dumps(saved),)
            )
        current = self.service.compounds(self.project.id)[0]
        self.assertEqual(current.descriptors.status, "failed")
        self.assertIsNone(effective_property_values(current)["molecular_weight"])
