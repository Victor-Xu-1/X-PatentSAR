"""Product tables/exports/SAR must not become a second anonymous source ledger."""

import json
import unittest

import test_structure_corpus as source_controls
from test_prediction_support import PredictionFixture

from patent_sar_extractor.web.models import Compound, Confidence, Source


class ProductTableScopeTests(PredictionFixture, unittest.TestCase):
    def test_anonymous_sources_stay_on_original_not_in_table_export_or_filters(self):
        source_controls.StructureCorpusTests.add_source(self)
        evidence = self.service.result_rows(self.project.id)
        anonymous = next(
            json.loads(row["payload"])
            for row in evidence
            if json.loads(row["payload"])["id"].startswith("source-structure:")
        )
        before = {
            path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()
        }
        with self.client() as client:
            prefix = f"/api/v1/projects/{self.project.id}"
            result = client.get(prefix + "/results")
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["total"], 1)
            self.assertNotIn(anonymous["id"], {r["id"] for r in result.json()["items"]})
            choices = client.get(
                prefix + "/filter-values", params={"column": "compound"}
            )
            self.assertNotIn(
                anonymous["display_id"], {r["value"] for r in choices.json()["items"]}
            )
            exported = client.post(prefix + "/export", json={"format": "json"})
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertEqual(len(exported.json()["items"]), 1)
            self.assertNotIn(
                anonymous["id"], {r["id"] for r in exported.json()["items"]}
            )
            refused = client.post(
                prefix + "/export",
                json={"format": "csv", "compound_ids": [anonymous["id"]]},
            )
            self.assertEqual(refused.status_code, 404, refused.text)
            # Retention and original diagnostics are not deleted by presentation policy.
            original = client.get(anonymous["structure_image_url"])
            self.assertEqual(original.status_code, 200, original.text)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(len(self.service.result_rows(self.project.id)), 2)

    def test_source_product_scope_is_not_chemistry_success_or_activity_presence(self):
        from patent_sar_extractor.web.product_records import is_numbered_product

        product = Compound(
            id="Compound I-255",
            display_id="Compound I-255",
            structure_id="drawn-product",
            record_kind="structure_only",
            activities=[],
            confidence=Confidence(level="high", reason="Controlled original owner"),
            source=Source(source_label="I-255", page=1),
        )
        self.assertTrue(is_numbered_product(product))
        for label in ("Intermediate 7", "中间体 7", "Intermediates 7"):
            rejected = product.model_copy(update={"source": Source(source_label=label)})
            self.assertFalse(is_numbered_product(rejected), label)
        for flag in (
            "unassociated_structure",
            "structure_number_unconfirmed",
            "ambiguous_binding",
            "structure_unmatched",
            "structure_not_generated",
            "structure_generation_failed",
        ):
            self.assertFalse(
                is_numbered_product(product.model_copy(update={"flags": [flag]}))
            )
        self.assertFalse(
            is_numbered_product(product.model_copy(update={"structure_id": None}))
        )
        self.assertFalse(
            is_numbered_product(
                product.model_copy(update={"record_kind": "activity_only"})
            )
        )


if __name__ == "__main__":
    unittest.main()
