"""Global table ordering is distinct from potency or candidate inference."""

import unittest
from types import SimpleNamespace

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.study_table import order_rows


class StudyTableTests(unittest.TestCase):
    def rows(self):
        return [
            SimpleNamespace(
                label=f"I-{index}",
                molecule_id=str(index),
                properties={"logP": 120 - index},
                priority_group=None,
                values={"m": [str(index)]},
            )
            for index in range(1, 121)
        ]

    def test_all_rows_order_before_page_slice_and_missing_stays_last(self):
        rows = self.rows()
        report = SimpleNamespace(policies=[])
        sorted_rows = order_rows(rows, report, "property:logP", "asc")
        self.assertEqual(sorted_rows[0].label, "I-120")
        self.assertEqual(sorted_rows[49].label, "I-71")
        rows[0].properties["logP"] = None
        self.assertEqual(
            order_rows(rows, report, "property:logP", "desc")[-1].label, "I-1"
        )
        self.assertEqual(rows[0].label, "I-1")

    def test_scalar_numeric_order_and_interval_uncertainty_is_not_a_midpoint(self):
        rows = self.rows()
        policy = SimpleNamespace(context_id="m", grade_order=[])
        report = SimpleNamespace(policies=[policy])
        rows[0].values["m"] = ["[0,2]"]
        ordered = order_rows(rows, report, "context:m", "desc")
        self.assertEqual(ordered[0].label, "I-120")
        self.assertEqual(ordered[-1].label, "I-1")

    def test_explicit_grade_order_and_source_ties(self):
        rows = self.rows()[:3]
        for row, grade in zip(rows, ["B", "A", "A"], strict=True):
            row.values["m"] = [grade]
        report = SimpleNamespace(
            policies=[SimpleNamespace(context_id="m", grade_order=["A", "B"])]
        )
        self.assertEqual(
            [row.label for row in order_rows(rows, report, "context:m")],
            ["I-2", "I-3", "I-1"],
        )
        with self.assertRaises(WebError):
            order_rows(rows, report, "context:foreign")


if __name__ == "__main__":
    unittest.main()
