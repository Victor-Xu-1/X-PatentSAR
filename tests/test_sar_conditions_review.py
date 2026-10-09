"""Declarations document facts on a selected source, not a boolean bypass."""

import unittest
from copy import deepcopy

from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.study_conditions import (
    declared_observation,
    validate_declarations,
)
from patent_sar_extractor.workers.study_candidates import collect_activities


class SARConditionReviewTests(unittest.TestCase):
    def setUp(self):
        self.dataset = {
            "source_kind": "project",
            "source_document_sha256": "a" * 64,
            "source_page_count": 20,
        }
        self.contexts = [
            {
                "id": "selected",
                "context": {
                    "target": None,
                    "assay": "Original assay",
                    "cell_line": None,
                    "duration": None,
                },
            }
        ]
        self.declaration = {
            "context_id": "selected",
            "fields": {"target": "Target T", "cell_line": "Cells C", "duration": "2 h"},
            "source_document_sha256": "a" * 64,
            "source_pages": [17, 18],
            "note": "Methods and source table checked. Declared research context, not automatic scientific acceptance.",
        }

    def test_only_missing_fields_can_be_documented_without_mutating_source(self):
        validate_declarations(
            self.dataset, self.contexts, ["selected"], [self.declaration]
        )
        original = {
            "metric_id": "m",
            "value": "1",
            "unit": "nM",
            "context": deepcopy(self.contexts[0]["context"]),
        }
        saved = deepcopy(original)
        result = declared_observation(original, self.declaration)
        self.assertEqual(original, saved)
        self.assertEqual(result["context"]["duration"], "2 h")
        self.assertEqual(result["context"]["assay"], "Original assay")
        self.assertTrue(result["_sar_declared_context"])

    def test_known_conditions_unit_or_unknown_replacements_are_rejected(self):
        for fields in [
            {"assay": "Changed assay"},
            {"unit": "uM"},
            {"duration": "unknown"},
        ]:
            with self.subTest(fields=fields), self.assertRaises(SARInputError):
                validate_declarations(
                    self.dataset,
                    self.contexts,
                    ["selected"],
                    [{**self.declaration, "fields": fields}],
                )

    def test_foreign_document_page_context_or_duplicate_claim_is_rejected(self):
        for changed in [
            {"source_document_sha256": "b" * 64},
            {"source_pages": [21]},
            {"context_id": "foreign"},
            {"source_pages": [17, 17]},
        ]:
            with self.subTest(changed=changed), self.assertRaises(SARInputError):
                validate_declarations(
                    self.dataset,
                    self.contexts,
                    ["selected"],
                    [{**self.declaration, **changed}],
                )
        with self.assertRaises(SARInputError):
            validate_declarations(
                self.dataset,
                self.contexts,
                ["selected"],
                [self.declaration, self.declaration],
            )

    def test_unrecorded_original_or_csv_cannot_acquire_patent_condition_proof(self):
        for changed in [
            {"source_kind": "csv"},
            {"source_page_count": None},
            {"source_document_sha256": None},
        ]:
            with self.subTest(changed=changed), self.assertRaises(SARInputError):
                validate_declarations(
                    {**self.dataset, **changed},
                    self.contexts,
                    ["selected"],
                    [self.declaration],
                )

    def test_declared_context_is_labelled_separately_and_boolean_confirmation_stays_insufficient(
        self,
    ):
        from patent_sar_extractor.core.sar.study_contexts import context_identity

        observation = {
            "metric_id": "m",
            "value": "1",
            "unit": "nM",
            "context": self.contexts[0]["context"],
        }
        identifier = context_identity(observation)
        policy = {"context_id": identifier, "direction": "lower", "grade_order": []}
        rows = [{"id": "1", "observations": [observation]}]
        _, unchanged = collect_activities(rows, [policy], True)
        self.assertEqual(unchanged[identifier]["1"]["evidence_basis"], "user_confirmed")
        _, documented = collect_activities(
            rows, [policy], False, [{**self.declaration, "context_id": identifier}]
        )
        self.assertEqual(
            documented[identifier]["1"]["evidence_basis"], "source_declared"
        )
        self.assertIn(
            "operator_declared_context_not_automatic_verification",
            documented[identifier]["1"]["reasons"],
        )
        self.assertIsNone(observation["context"]["duration"])


if __name__ == "__main__":
    unittest.main()
