"""Focused regression contracts for a complete, source-number-led workflow."""

from __future__ import annotations

import unittest

from patent_sar_extractor import contracts
from patent_sar_extractor.application.activity_policy import (
    _activity_acceptance_errors,
    _expand_cpd_labels,
    _normalize_cpd_label,
)


class SourceFirstContractTests(unittest.TestCase):
    def empty_activity(self) -> dict:
        return {
            **contracts.artifact_identity(
                contracts.ACTIVITY_SCHEMA, contracts.ACTIVITY_SCHEMA_VERSION
            ),
            "rows": [],
            "data": {},
        }

    def test_product_stays_v010(self):
        self.assertEqual(contracts.__version__, "0.1.0")
        self.assertEqual(contracts.PRODUCT_NAME, "X-PatentSAR")

    def test_one_source_first_stage_order(self):
        self.assertEqual(
            contracts.CORE_STAGE_ORDER,
            (
                "classify",
                "locate",
                "structures",
                "bind",
                "activity",
                "smiles",
                "final",
                "qa",
            ),
        )

    def test_proved_no_activity_does_not_block_structures(self):
        self.assertEqual(
            _activity_acceptance_errors(
                self.empty_activity(), [], classified_activity_pages=[]
            ),
            [],
        )

    def test_missing_values_on_declared_activity_pages_stay_failure(self):
        errors = _activity_acceptance_errors(
            self.empty_activity(), [], classified_activity_pages=[7]
        )
        self.assertTrue(errors)

    def test_unproved_empty_extraction_cannot_be_called_absence(self):
        self.assertTrue(_activity_acceptance_errors(self.empty_activity(), []))

    def test_identifier_never_truncates_or_splits_composite_measurement(self):
        self.assertEqual(_normalize_cpd_label("Compound 1-2-3A"), "Compound 1-2-3A")
        self.assertEqual(_normalize_cpd_label("Cmpd 42"), "Compound 42")
        self.assertEqual(_expand_cpd_labels("Compound 1/2"), ["Compound 1/2"])


if __name__ == "__main__":
    unittest.main()
