"""Descriptive arithmetic is not a potency policy or a best-repeat choice."""

import copy
import unittest

from pydantic import ValidationError

from patent_sar_extractor.core.sar.observation_pair import recorded_difference
from patent_sar_extractor.web.sar.preview_models import RecordedDifference

CONTEXT = {
    "target": "not_applicable",
    "assay": "PK",
    "cell_line": "not_applicable",
    "duration": "24 h",
    "species": "rat",
}


def observation(value, **changes):
    return {
        "metric_id": "recorded",
        "value": value,
        "unit": "mL/min/kg",
        "context": dict(CONTEXT),
        **changes,
    }


class RecordedDifferenceTests(unittest.TestCase):
    def test_exact_signed_zero_and_decimal_arithmetic_without_direction(self):
        for left, right, delta in [
            ("2", "5", 3),
            ("5", "2", -3),
            ("-2", "-1", 1),
            ("0", "0", 0),
            ("1.000000000000000000000000001", "1.000000000000000000000000002", 1e-27),
        ]:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    recorded_difference(
                        [observation(left)], [observation(right)], "recorded"
                    ),
                    {"status": "comparable", "value": delta},
                )

    def test_no_missing_interval_grade_overflow_or_underflow_difference(self):
        for left, right, status in [
            ("ND", "3", "missing"),
            ("<6", "2", "not_scalar"),
            ("[1,3]", "[4,5]", "not_scalar"),
            ("A", "B", "indeterminate"),
            ("-1e308", "1e308", "not_representable"),
            ("1e-308", "1.000000000000000000000000001e-308", "not_representable"),
        ]:
            with self.subTest(left=left):
                self.assertEqual(
                    recorded_difference(
                        [observation(left)], [observation(right)], "recorded"
                    ),
                    {"status": status, "value": None},
                )
        self.assertEqual(
            recorded_difference([], [observation("2")], "recorded")["status"], "missing"
        )

    def test_all_conditions_and_units_must_match_without_inherited_confirmation(self):
        for field in CONTEXT:
            right = observation("3", context={**CONTEXT, field: "different"})
            self.assertEqual(
                recorded_difference([observation("2")], [right], "recorded")["status"],
                "context_mismatch",
            )
        for right, status in [
            (observation("3", unit="L/h/kg"), "context_mismatch"),
            (observation("3", unit=None), "indeterminate"),
            (observation("3", context={}), "indeterminate"),
        ]:
            self.assertEqual(
                recorded_difference([observation("2")], [right], "recorded"),
                {"status": status, "value": None},
            )

    def test_repeats_never_average_and_inputs_never_change(self):
        left = [observation("2"), observation("2.0")]
        right = [observation("5")]
        original = copy.deepcopy((left, right))
        self.assertEqual(recorded_difference(left, right, "recorded")["value"], 3)
        self.assertEqual((left, right), original)
        for extra in ["3", "", "ND", ">2"]:
            self.assertEqual(
                recorded_difference(left + [observation(extra)], right, "recorded")[
                    "status"
                ],
                "indeterminate",
            )

    def test_explicit_inline_unit_uses_existing_measurement_authority(self):
        self.assertEqual(
            recorded_difference(
                [observation("10 nM", unit="nM")],
                [observation("0.002 uM", unit="nM")],
                "recorded",
            ),
            {"status": "comparable", "value": -8},
        )
        # Time/PK conversions are not silently introduced by arithmetic.
        self.assertEqual(
            recorded_difference(
                [observation("1 h", unit="h")],
                [observation("120 min", unit="h")],
                "recorded",
            )["status"],
            "indeterminate",
        )

    def test_dto_cannot_forge_a_difference_or_rank(self):
        for item in [
            {"status": "comparable", "value": None},
            {"status": "missing", "value": 0},
            {"status": "better", "value": 3},
            {"status": "comparable", "value": float("inf")},
        ]:
            with self.subTest(item=item), self.assertRaises(ValidationError):
                RecordedDifference.model_validate(item)
