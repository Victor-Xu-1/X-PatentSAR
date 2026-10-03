"""Workbook APIs use complete effective rows and existing prediction records."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from test_prediction_support import PredictionFixture, controlled_summary

from patent_sar_extractor.web.activity_columns import (
    activity_column_id,
    activity_context,
)
from patent_sar_extractor.web.models import Error
from patent_sar_extractor.web.prediction_models import PredictionSummary
from patent_sar_extractor.web.prediction_storage import smiles_digest


class TableQueryAPITests(PredictionFixture, unittest.TestCase):
    def test_get_and_export_share_the_same_typed_column_filters(self):
        row = self.service.results(self.project.id).items[0]
        column = activity_column_id(activity_context(row.activities[0]))
        criterion = [{"column": f"activity:{column}", "op": "gte", "value": "2"}]
        params = {
            "column_filters": json.dumps(criterion),
            "sort_column": "compound",
            "sort_direction": "desc",
        }
        with self.client() as client:
            endpoint = f"/api/v1/projects/{self.project.id}"
            result = client.get(endpoint + "/results", params=params)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["total"], 0)
            original = client.get(endpoint + "/results").json()
            self.assertEqual(
                result.json()["activity_columns"], original["activity_columns"]
            )
            exported = client.post(
                endpoint + "/export",
                params=params,
                json={"format": "json", "compound_ids": []},
            )
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertEqual(exported.json()["items"], [])

    def test_invalid_filters_fail_even_when_search_returns_no_rows(self):
        row = self.service.results(self.project.id).items[0]
        column = activity_column_id(activity_context(row.activities[0]))
        with self.client() as client:
            endpoint = f"/api/v1/projects/{self.project.id}/results"
            for criteria in (
                [{"column": f"activity:{column}", "op": "gt", "value": "NaN"}],
                [
                    {
                        "column": "compound; DROP TABLE compounds",
                        "op": "eq",
                        "value": "1",
                    }
                ],
                [{"column": "compound", "op": "in", "values": ["1"] * 201}],
            ):
                with self.subTest(criteria=criteria):
                    response = client.get(
                        endpoint,
                        params={
                            "q": "no matching row",
                            "column_filters": json.dumps(criteria),
                        },
                    )
                    self.assertEqual(response.status_code, 422, response.text)

    def test_property_filter_reads_current_predictions_without_running_a_model(self):
        row = self.service.results(self.project.id).items[0]
        producer, _, source = self.draft()
        self.service.predictions.put(
            self.project.id,
            row.id,
            controlled_summary(source, row.smiles, producer["id"]),
        )
        with patch(
            "patent_sar_extractor.web.prediction_jobs.enqueue_prediction",
            side_effect=AssertionError("Filtering must not enqueue inference"),
        ):
            results = self.service.results(
                self.project.id,
                column_filters=json.dumps(
                    [{"column": "property:molecular_weight", "op": "not_empty"}]
                ),
                sort_column="property:molecular_weight",
                sort_direction="desc",
            )
        self.assertEqual(results.total, 1)
        self.assertEqual(results.items[0].admet.status, "complete")
        self.assertTrue(results.items[0].admet.properties)
        self.service.predictions.put(
            self.project.id,
            row.id,
            PredictionSummary(
                status="failed",
                source_fingerprint=source,
                smiles_sha256=smiles_digest(row.smiles),
                job_id=producer["id"],
                error=Error(
                    code="controlled_failure", message="Explicit controlled failure"
                ),
            ),
        )
        self.assertEqual(
            self.service.results(
                self.project.id,
                column_filters=json.dumps(
                    [{"column": "property:molecular_weight", "op": "not_empty"}]
                ),
            ).total,
            0,
        )
