"""Produced ID catalogs join activities, not anonymous crop display aliases."""

from __future__ import annotations

import json
import unittest

from test_prediction_support import PredictionFixture

from patent_sar_extractor.core.binding_catalog import compound_catalog
from patent_sar_extractor.web.acceptance import ARTIFACTS
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.exports import export_json


class CompoundCatalogViewTests(PredictionFixture, unittest.TestCase):
    def catalog_run(self):
        binding_path = self.run / ARTIFACTS["bindings"][0]
        payload = json.loads(binding_path.read_text())
        first = payload["final_bindings"][0]
        second = {
            **first,
            "cpd": "Compound 8",
            "compound_id": "Compound 8",
            "structure_id": "numbered-without-activity",
            "authoritative_table_source_label": "Compound 8",
        }
        repeat = {**first, "structure_id": "proved-reprint"}
        payload["compound_catalog"] = compound_catalog([first, second], [repeat])
        binding_path.write_text(json.dumps(payload))
        path = self.run / ARTIFACTS["structures"][0]
        structures = json.loads(path.read_text())
        original = structures["structures"][0]
        structures["structures"].extend(
            {**original, "structure_id": item["structure_id"]}
            for item in (second, repeat)
        )
        path.write_text(json.dumps(structures))
        return binding_path, payload

    def test_numbered_source_without_activity_is_a_primary_row_reprint_is_not(self):
        self.catalog_run()
        before = {
            path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()
        }
        self.service.refresh(self.project.id)
        results = self.service.results(self.project.id)
        self.assertEqual(
            [row.id for row in results.items], ["Compound 1", "Compound 8"]
        )
        first, second = results.items
        self.assertEqual(len(first.additional_sources), 1)
        self.assertEqual(first.additional_sources[0].source_label, "Compound 1")
        self.assertEqual(first.additional_sources[0].page, 1)
        self.assertEqual(len(first.activities), 1)
        self.assertEqual(second.activities, [])
        self.assertEqual(second.display_id, "Compound 8")
        self.assertEqual(second.record_kind, "structure_only")
        self.assertEqual(second.confidence.level, "high")
        self.assertTrue(second.structure_image_url)
        self.assertEqual(second.recognition.status, "not_run")
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        exported = json.loads(
            b"".join(export_json(self.service.project(self.project.id), results.items))
        )
        self.assertEqual(
            exported["formal_acceptance_scope"], "original_activity_association_only"
        )

    def test_zero_activity_still_retains_confirmed_printed_identifiers(self):
        path, payload = self.catalog_run()
        payload["final_bindings"] = []
        path.write_text(json.dumps(payload))
        activity_path = self.run / ARTIFACTS["activity"][0]
        activity = json.loads(activity_path.read_text())
        activity.update(active_cpds=[], rows=[])
        activity_path.write_text(json.dumps(activity))
        self.service.refresh(self.project.id)
        results = self.service.results(self.project.id)
        self.assertEqual(
            [row.display_id for row in results.items], ["Compound 1", "Compound 8"]
        )
        self.assertTrue(
            all(row.record_kind == "structure_only" for row in results.items)
        )
        self.assertTrue(all(not row.activities for row in results.items))

    def test_cross_owner_reprint_is_rejected_instead_of_silently_merged(self):
        path, payload = self.catalog_run()
        payload["compound_catalog"]["entries"][0]["additional_sources"][0]["cpd"] = (
            "Compound 8"
        )
        path.write_text(json.dumps(payload))
        with self.assertRaises(WebError) as error:
            self.service.refresh(self.project.id)
        self.assertEqual(error.exception.code, "invalid_compound_catalog")

    def test_one_source_cannot_be_owned_by_two_printed_identifiers(self):
        path, payload = self.catalog_run()
        entries = payload["compound_catalog"]["entries"]
        entries[1]["structure_id"] = entries[0]["structure_id"]
        path.write_text(json.dumps(payload))
        with self.assertRaises(WebError) as error:
            self.service.refresh(self.project.id)
        self.assertEqual(error.exception.code, "invalid_compound_catalog")

    def test_malformed_nested_proof_is_a_safe_validation_error(self):
        path, payload = self.catalog_run()
        payload["compound_catalog"]["entries"][0]["visible_label_candidates"] = [None]
        path.write_text(json.dumps(payload))
        with self.assertRaises(WebError) as error:
            self.service.refresh(self.project.id)
        self.assertEqual(error.exception.code, "invalid_compound_catalog")

    def test_boolean_schema_version_is_not_an_integer_contract(self):
        path, payload = self.catalog_run()
        payload["compound_catalog"]["schema"]["version"] = True
        path.write_text(json.dumps(payload))
        with self.assertRaises(WebError) as error:
            self.service.refresh(self.project.id)
        self.assertEqual(error.exception.code, "invalid_compound_catalog")
