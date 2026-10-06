"""Printed dash/suffix identifiers use one stable natural ordering."""

import unittest
from unittest.mock import patch

from patent_sar_extractor.core.binding_catalog import compound_catalog


class CatalogOrderTests(unittest.TestCase):
    def test_dashes_are_not_concatenated_into_another_number(self):
        labels = ["10", "2", "1-2", "1", "8B", "8A", "1-1"]
        records = [
            {"cpd": f"Compound {label}", "structure_id": f"s-{label}"}
            for label in labels
        ]
        with patch(
            "patent_sar_extractor.core.binding_catalog.annotate_binding_accuracy",
            side_effect=lambda row: {
                **row,
                "accuracy_status": "confirmed",
                "fail_closed": False,
            },
        ):
            result = compound_catalog(records, [])
        self.assertEqual(
            [r["cpd"] for r in result["entries"]],
            [
                "Compound 1",
                "Compound 1-1",
                "Compound 1-2",
                "Compound 2",
                "Compound 8A",
                "Compound 8B",
                "Compound 10",
            ],
        )
