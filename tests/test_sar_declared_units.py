"""Exact declared-unit readings for generic SAR/PK, never guessed conversions."""

import copy
import unittest
from decimal import Decimal, Inexact, localcontext

from test_sar_statistics import CONTEXT, observation

from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.measurements import (
    explicit_unit_basis,
    parse_measurement,
)
from patent_sar_extractor.core.sar.observation_pair import recorded_difference
from patent_sar_extractor.core.sar.statistics import compare_observations
from patent_sar_extractor.core.sar.study_statistics import assess
from patent_sar_extractor.core.sar.values import parse_value


class DeclaredUnitTests(unittest.TestCase):
    def test_shared_parser_accepts_only_the_exact_declared_suffix(self):
        for unit in (
            "mL/min/kg",
            "h",
            "ng·h/mL",
            "mg/L",
            "s^-1",
            "10^6 cells",
            "score",
            "s/mM",
        ):
            for separator in (
                (" ", "\u00a0") if unit[0].isdigit() else (" ", "", "\u00a0")
            ):
                with self.subTest(unit=unit, separator=separator):
                    value = parse_measurement("2.50" + separator + unit, {}, unit)
                    self.assertEqual(value.low, Decimal("2.50"))
                    self.assertEqual(value.kind, "scalar")

    def test_bounds_and_scientific_notation_are_not_rounded_or_closed(self):
        for raw, expected in (
            ("<2 h", "<2"),
            ("≥2 h", ">=2"),
            ("[1,2) h", "[1,2)"),
            ("1.5e-2h", "0.015"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(
                    parse_measurement(raw, {}, "h"), parse_value(expected, {})
                )
        raw = "0.10000000000000000000000000000000000000001 mL/min/kg"
        with localcontext() as context:
            context.prec = 3
            context.traps[Inexact] = True
            value = parse_measurement(raw, {}, "mL/min/kg")
        self.assertEqual(value.low, Decimal(raw.split()[0]))

    def test_recorded_pk_difference_preserves_original_text_and_conditions(self):
        left = [observation("2 mL/min/kg", unit="mL/min/kg")]
        right = [observation("5mL/min/kg", unit="mL/min/kg")]
        before = copy.deepcopy((left, right))
        self.assertEqual(
            recorded_difference(left, right, "potency"),
            {"status": "comparable", "value": 3.0},
        )
        self.assertEqual((left, right), before)

    def test_selected_pair_and_study_assessment_share_the_same_parser(self):
        left = [observation("2 h", unit="h"), observation("2", unit="h")]
        right = [observation("5 h", unit="h")]
        result = compare_observations(left, right, "potency", "higher", [], False)
        self.assertEqual(result["comparison"], "better")
        self.assertEqual(result["fold_change"], 2.5)
        self.assertIn("repeated_measurements", result["reasons"])
        self.assertEqual(result["reference_values"], ["2 h", "2"])
        state = assess(
            left,
            {
                "direction": "higher",
                "grade_order": [],
                "strength_method": "unclassified",
            },
            False,
        )
        self.assertEqual(state["status"], "scalar")
        self.assertFalse(state["strong"])

    def test_no_inference_from_units_case_footnotes_or_unmatched_suffixes(self):
        for raw, unit in (
            ("2 h", None),
            ("2 min", "h"),
            ("2 ml/min/kg", "mL/min/kg"),
            ("2 mL/min/kg*", "mL/min/kg"),
            ("2 mg/L", "ng/mL"),
            ("2 h extra", "h"),
            ("2 mg/mL", "mL"),
            ("2 h", "unknown"),
            ("1,000 h", "h"),
            ("A h", "h"),
        ):
            with self.subTest(raw=raw, unit=unit), self.assertRaises(SARInputError):
                parse_measurement(raw, {}, unit)
        self.assertIsNone(explicit_unit_basis("2 mL/min/kg"))
        self.assertIsNone(explicit_unit_basis("2 h"))

    def test_declared_numeric_unit_does_not_truncate_bare_values(self):
        for raw in ("11", "1.1", "1e1"):
            self.assertEqual(parse_measurement(raw, {}, "1"), parse_value(raw, {}))
        self.assertEqual(parse_measurement("2 h", {"2 h": 0}, "h").kind, "ordinal")

    def test_existing_molar_conversion_and_old_input_policy_are_retained(self):
        self.assertEqual(parse_measurement("0.002 µM", {}, "nM").low, Decimal(2))
        self.assertEqual(parse_measurement("80％", {}, "%").low, Decimal(80))
        with self.assertRaises(SARInputError):
            parse_measurement("2 h", {}, "h", declared_units=False)
        with self.assertRaises(SARInputError):
            parse_measurement("2 h", {}, "h", inline_units=False)
        self.assertEqual(
            parse_measurement("0.002 µM", {}, "nM", declared_units=False).low,
            Decimal(2),
        )

    def test_context_conflict_missing_and_conflicting_repeats_still_withhold_delta(
        self,
    ):
        left = [observation("2 h", unit="h")]
        cases = [
            [observation("5 h", unit="h", context={**CONTEXT, "cell_line": "other"})],
            [observation("5 h", unit="h", context={**CONTEXT, "duration": None})],
            [observation("", unit="h")],
            [observation("5 h", unit="h"), observation("6 h", unit="h")],
            [observation("5 h", unit="h"), observation("", unit="h")],
            [observation("<5 h", unit="h")],
        ]
        for right in cases:
            with self.subTest(right=right):
                self.assertIsNone(recorded_difference(left, right, "potency")["value"])


if __name__ == "__main__":
    unittest.main()
