"""Explicit source-unit interpretation without rewriting readings or guessing units."""

from __future__ import annotations

import unittest
from decimal import Decimal, Inexact, localcontext

from test_sar_statistics import compare, observation

from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.measurements import (
    explicit_unit_basis,
    parse_measurement,
)
from patent_sar_extractor.core.sar.values import parse_value


class MeasurementUnitTests(unittest.TestCase):
    def test_intake_basis_requires_an_explicit_numeric_unit_in_that_cell(self):
        for raw, expected in (
            ("10 nM", "nM"),
            ("<0.01 µM", "nM"),
            ("80%", "%"),
            ("10", None),
            ("ND", None),
            ("A nM", None),
            ("1 mg/mL", None),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(explicit_unit_basis(raw), expected)

    def test_pair_comparison_uses_units_but_preserves_source_text(self):
        result = compare([observation("10 nM")], [observation("0.002 uM")])
        self.assertEqual(result["comparison"], "better")
        self.assertEqual(result["fold_change"], 5.0)
        self.assertEqual(result["reference_values"], ["10 nM"])
        self.assertEqual(result["candidate_values"], ["0.002 uM"])

    def test_molar_aliases_and_exact_scaling_in_the_declared_unit(self):
        for raw, declared, expected in (
            ("10 nM", "nM", "10"),
            ("0.002 uM", "nM", "2"),
            ("0.002 µM", "nM", "2"),
            ("0.002 μM", "nM", "2"),
            ("1e-3 M", "mM", "1"),
            ("2500 pM", "nM", "2.5"),
            ("10nM", "uM", "0.01"),
            ("80 %", "%", "80"),
            ("80％", "percent", "80"),
        ):
            with self.subTest(raw=raw, declared=declared):
                value = parse_measurement(raw, {}, declared)
                self.assertEqual(value.kind, "scalar")
                self.assertEqual(value.low, Decimal(expected))

    def test_ranges_and_censored_bounds_preserve_inclusion(self):
        for raw, expected in (
            ("<0.01 uM", "<10"),
            ("≥0.01 μM", ">=10"),
            ("[0.001,0.01) µM", "[1,10)"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(
                    parse_measurement(raw, {}, "nM"), parse_value(expected, {})
                )

    def test_conversion_does_not_depend_on_process_decimal_rounding(self):
        raw = "0.001000000000000000000000000000000000000000001 uM"
        with localcontext() as context:
            context.prec = 3
            context.traps[Inexact] = True
            value = parse_measurement(raw, {}, "nM")
        self.assertEqual(
            value.low, Decimal("1.000000000000000000000000000000000000000001")
        )

    def test_units_are_not_inferred_or_coerced_across_dimensions(self):
        for raw, unit in (
            ("10 nM", None),
            ("10 nM", "%"),
            ("10 %", "nM"),
            ("10 mg/mL", "nM"),
            ("10 nm", "nM"),
            ("10 nM*", "nM"),
            ("1,000 nM", "nM"),
        ):
            with self.subTest(raw=raw, unit=unit), self.assertRaises(SARInputError):
                parse_measurement(raw, {}, unit)

    def test_bare_values_explicit_grades_and_legacy_reads_keep_their_semantics(self):
        for raw in ("10", "<10", "ND", "[1,2)"):
            self.assertEqual(parse_measurement(raw, {}, "nM"), parse_value(raw, {}))
        self.assertEqual(
            parse_measurement("A", {"A": 0}, None), parse_value("A", {"A": 0})
        )
        self.assertEqual(parse_measurement("10 nM", {"10 nM": 0}, None).kind, "ordinal")
        with self.assertRaises(SARInputError):
            parse_measurement("10 nM", {}, "nM", inline_units=False)

    def test_converted_numeric_limits_are_explicit_not_zero_or_infinity(self):
        for raw, unit in (("1e308 M", "nM"), ("1e-308 fM", "M")):
            with self.subTest(raw=raw), self.assertRaises(SARInputError):
                parse_measurement(raw, {}, unit)


if __name__ == "__main__":
    unittest.main()
