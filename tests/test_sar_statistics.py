"""Scalar/interval/ordinal evidence, without inferred assay or grade semantics."""

from __future__ import annotations

import copy
import unittest
from decimal import Inexact, localcontext

from patent_sar_extractor.core.sar.limits import MAX_OBSERVATIONS
from patent_sar_extractor.core.sar.statistics import compare_observations
from patent_sar_extractor.web.sar.models import Observation, Pair

CONTEXT = {
    "target": "receptor",
    "assay": "binding",
    "cell_line": "not_applicable",
    "duration": "30 min",
}


def observation(value, *, context=None, unit="nM", metric_id="potency"):
    return {
        "metric_id": metric_id,
        "value": value,
        "unit": unit,
        "context": dict(CONTEXT if context is None else context),
        "source_kind": "imported",
    }


def compare(left, right, **options):
    return compare_observations(
        left,
        right,
        "potency",
        options.get("direction", "lower"),
        options.get("grade_order", []),
        options.get("confirm_context", False),
    )


class StatisticsTests(unittest.TestCase):
    def test_exact_positive_scalars_and_direction(self):
        result = compare([observation("10")], [observation("2")])
        self.assertEqual(result["comparison"], "better")
        self.assertEqual(result["fold_change"], 5.0)
        self.assertEqual(result["evidence_basis"], "recorded_context")
        self.assertEqual(
            compare([observation("10")], [observation("2")], direction="higher")[
                "comparison"
            ],
            "worse",
        )

    def test_strictly_separated_intervals_only(self):
        result = compare([observation(">10")], [observation("<2")])
        self.assertEqual(result["comparison"], "better")
        self.assertIsNone(result["fold_change"])
        for left, right in (("<10", "<2"), ("[2,10]", "[1,3]"), (">10", "<10")):
            with self.subTest(left=left, right=right):
                result = compare([observation(left)], [observation(right)])
                self.assertEqual(result["comparison"], "indeterminate")
                self.assertIsNone(result["fold_change"])

    def test_explicit_strongest_first_grades_not_numeric_thresholds(self):
        left, right = [observation("G", unit=None)], [observation("A", unit=None)]
        self.assertEqual(
            compare(left, right, grade_order=["A", "G"])["comparison"], "better"
        )
        self.assertEqual(compare(left, right)["comparison"], "indeterminate")
        same = compare(right, right, grade_order=["A", "G"])
        self.assertEqual(same["comparison"], "indeterminate")
        self.assertIsNone(same["fold_change"])

    def test_missing_context_and_known_conflicts(self):
        left, right = [observation("10", context={})], [observation("2", context={})]
        self.assertEqual(compare(left, right)["evidence_basis"], "insufficient")
        result = compare(left, right, confirm_context=True)
        self.assertEqual(result["comparison"], "better")
        self.assertEqual(result["evidence_basis"], "user_confirmed")
        right[0]["context"] = {**CONTEXT, "duration": "60 min"}
        self.assertEqual(
            compare([observation("10")], right, confirm_context=True)["comparison"],
            "context_mismatch",
        )
        self.assertEqual(
            compare(
                [observation("10")], [observation("2", unit="uM")], confirm_context=True
            )["comparison"],
            "context_mismatch",
        )

    def test_conflict_repeat_and_missing_are_not_averaged(self):
        left = [observation("10"), observation("20")]
        right = [observation("2")]
        result = compare(left, right)
        self.assertEqual(result["comparison"], "indeterminate")
        self.assertEqual(result["reference_values"], ["10", "20"])
        self.assertIn("conflicting_measurements", result["reasons"])
        repeated = compare([observation("10"), observation("10.0")], right)
        self.assertEqual(repeated["comparison"], "better")
        self.assertIn("repeated_measurements", repeated["reasons"])
        self.assertEqual(compare([observation("ND")], right)["comparison"], "missing")

    def test_observations_are_immutable(self):
        left, right = [observation("10")], [observation("2")]
        before = copy.deepcopy((left, right))
        compare(left, right)
        self.assertEqual((left, right), before)

    def test_known_conflicts_take_priority_over_unparseable_values(self):
        right = [observation("unresolved", unit="uM")]
        self.assertEqual(
            compare([observation("10")], right, confirm_context=True)["comparison"],
            "context_mismatch",
        )

    def test_invalid_direction_and_decimal_environment_fail_closed(self):
        left, right = [observation("10")], [observation("3")]
        self.assertEqual(
            compare(left, right, direction=[])["comparison"], "indeterminate"
        )
        with localcontext() as context:
            context.traps[Inexact] = True
            result = compare(left, right)
        self.assertAlmostEqual(result["fold_change"], 10 / 3)

    def test_all_recorded_fields_not_only_target_and_assay(self):
        context = {
            **CONTEXT,
            "species": "human",
            "pH": "7.4",
            "temperature": "25 C",
            "substrate": "probe",
        }
        for field in context:
            candidate = {**context, field: "different"}
            with self.subTest(field=field):
                result = compare(
                    [observation("10", context=context)],
                    [observation("2", context=candidate)],
                    confirm_context=True,
                )
                self.assertEqual(result["comparison"], "context_mismatch")
                self.assertEqual(result["evidence_basis"], "insufficient")
                self.assertIsNone(result["fold_change"])

    def test_partial_conditions_require_confirmation(self):
        partial = {**CONTEXT, "duration": None}
        for confirmed, basis, status in (
            (False, "insufficient", "indeterminate"),
            (True, "user_confirmed", "better"),
        ):
            result = compare(
                [observation("10")],
                [observation("2", context=partial)],
                confirm_context=confirmed,
            )
            self.assertEqual(result["comparison"], status)
            self.assertEqual(result["evidence_basis"], basis)
        missing_extra = {**CONTEXT, "temperature": "25 C"}
        self.assertEqual(
            compare([observation("10", context=missing_extra)], [observation("2")])[
                "comparison"
            ],
            "indeterminate",
        )
        explicit_unknown = {**CONTEXT, "duration": "unknown"}
        self.assertEqual(
            compare(
                [observation("10", context=explicit_unknown)],
                [observation("2", context=explicit_unknown)],
            )["evidence_basis"],
            "insufficient",
        )

    def test_units_are_exact_no_implicit_conversion_or_inline_guess(self):
        for unit in ("uM", "nm", "µM", "mg/mL"):
            result = compare(
                [observation("10")],
                [observation("0.002", unit=unit)],
                confirm_context=True,
            )
            self.assertEqual(result["comparison"], "context_mismatch")
            self.assertIn("unit_conflict", result["reasons"])
        self.assertEqual(
            compare([observation("10 nM")], [observation("2")])["comparison"],
            "indeterminate",
        )
        redundant = {**CONTEXT, "unit": "uM"}
        self.assertEqual(
            compare(
                [observation("10", context=redundant)],
                [observation("2", context=redundant)],
                confirm_context=True,
            )["comparison"],
            "context_mismatch",
        )

    def test_missing_units_are_insufficient_without_explicit_confirmation(self):
        left, right = [observation("10", unit=None)], [observation("2", unit=None)]
        self.assertEqual(compare(left, right)["evidence_basis"], "insufficient")
        result = compare(left, right, confirm_context=True)
        self.assertEqual(result["comparison"], "better")
        self.assertEqual(result["evidence_basis"], "user_confirmed")
        self.assertIn("unit_missing", result["reasons"])

    def test_interval_syntax_and_both_numeric_directions(self):
        for left, right in (
            ("10–20", "1-2"),
            ("[10,20]", "(1,2]"),
            ("≥10", "≤2"),
            ("10", "<2"),
            (">10", "2"),
            ("-10--5", "-20--15"),
        ):
            for direction, expected in (("lower", "better"), ("higher", "worse")):
                with self.subTest(left=left, right=right, direction=direction):
                    result = compare(
                        [observation(left)], [observation(right)], direction=direction
                    )
                    self.assertEqual(result["comparison"], expected)
                    self.assertIsNone(result["fold_change"])
        for value in ("20-10", "(10,10)", "10 ± 2", "NaN", "Infinity", "1e309"):
            result = compare([observation(value)], [observation("2")])
            self.assertEqual(result["comparison"], "indeterminate")
            self.assertIsNone(result["fold_change"])

    def test_equal_intervals_and_boundary_touching_are_not_exact_scalars(self):
        for left, right in (
            ("[10,10]", "10"),
            ("10-20", "10-20"),
            ("≤10", "≥10"),
            ("[1,2]", "[2,3]"),
        ):
            with self.subTest(left=left, right=right):
                result = compare([observation(left)], [observation(right)])
                self.assertEqual(result["comparison"], "indeterminate")
                self.assertIsNone(result["fold_change"])

    def test_grade_ranking_is_only_explicit_strongest_first(self):
        left, right = [observation("G", unit=None)], [observation("A", unit=None)]
        for direction in ("lower", "higher"):
            result = compare(left, right, direction=direction, grade_order=["G", "A"])
            self.assertEqual(result["comparison"], "worse")
            self.assertIsNone(result["fold_change"])
        numeric = compare(
            [observation("1")], [observation("2")], grade_order=["2", "1"]
        )
        self.assertEqual(numeric["comparison"], "better")
        self.assertIsNone(numeric["fold_change"])
        mixed = compare([observation("A")], [observation("2")], grade_order=["A", "G"])
        self.assertIn("mixed_measurement_kinds", mixed["reasons"])
        for order in (("A", "A"), ["A", " G"], ["A"] * 33, [1], None):
            result = compare(left, right, grade_order=order)
            self.assertEqual(result["comparison"], "indeterminate")

    def test_fold_exact_positive_scalars_only_and_finite(self):
        for left, right, direction, status in (
            ("-10", "-20", "lower", "better"),
            ("0", "0", "lower", "equal"),
            ("1e308", "1e-308", "lower", "better"),
            ("1e308", "1e-308", "higher", "worse"),
        ):
            result = compare(
                [observation(left)], [observation(right)], direction=direction
            )
            self.assertEqual(result["comparison"], status)
            self.assertIsNone(result["fold_change"])
        result = compare([observation("2")], [observation("10")], direction="higher")
        self.assertEqual(result["fold_change"], 5.0)
        result = compare([observation("1e-2")], [observation("0.01")])
        self.assertEqual(result["comparison"], "equal")
        self.assertEqual(result["fold_change"], 1.0)

    def test_repeated_different_contexts_are_not_best_only(self):
        left = [
            observation("10"),
            observation("10", context={**CONTEXT, "assay": "functional"}),
        ]
        self.assertEqual(
            compare(left, [observation("2")], confirm_context=True)["comparison"],
            "context_mismatch",
        )
        partial = compare([observation("10"), observation("ND")], [observation("2")])
        self.assertEqual(partial["comparison"], "indeterminate")
        self.assertIn("partial_missing_measurements", partial["reasons"])
        repeated_grade = compare(
            [observation("A"), observation("A")],
            [observation("A")],
            grade_order=["A", "G"],
        )
        self.assertEqual(repeated_grade["comparison"], "indeterminate")
        self.assertIn("repeated_measurements", repeated_grade["reasons"])
        self.assertIsNone(repeated_grade["fold_change"])

    def test_missing_and_metric_selection_preserve_every_raw_value(self):
        result = compare([], [observation("2")])
        self.assertEqual(result["comparison"], "missing")
        self.assertEqual(result["reference_values"], [])
        left = [
            observation(" 10 "),
            observation("unrelated", metric_id="other"),
            observation("10.0"),
        ]
        result = compare(left, [observation("2")])
        self.assertEqual(result["reference_values"], [" 10 ", "10.0"])
        self.assertEqual(result["comparison"], "better")
        for value in ("", "NA", "N/A", "ND", "NT", "—"):
            result = compare([observation(value)], [observation("2")])
            self.assertEqual(result["comparison"], "missing")
            self.assertEqual(result["reference_values"], [value])

    def test_bounds_and_malformed_observations_return_only_safe_codes(self):
        for packet in (
            None,
            ["raw <script>"],
            [{"metric_id": "potency", "value": None}],
            [observation("10", context={"target": {"raw": "secret"}})],
            [observation("10", unit=[])],
            [observation("x" * 257)],
            [observation("10")] * (MAX_OBSERVATIONS + 1),
        ):
            with self.subTest(packet_type=type(packet)):
                result = compare(packet, [observation("2")], confirm_context=True)
                self.assertEqual(result["comparison"], "indeterminate")
                self.assertEqual(result["evidence_basis"], "insufficient")
                self.assertTrue(
                    all(code.replace("_", "").isalnum() for code in result["reasons"])
                )
        self.assertEqual(
            compare([observation("10")], [observation("2")], confirm_context="true")[
                "comparison"
            ],
            "indeterminate",
        )

    def test_shared_observation_and_pair_dto_contract(self):
        reference = Observation(
            metric_id="potency",
            value="10",
            unit="nM",
            context=CONTEXT,
            source_page=4,
            source_row=8,
        ).model_dump()
        candidate = Observation(
            metric_id="potency", value="2", unit="nM", context=CONTEXT
        ).model_dump()
        result = compare([reference], [candidate])
        pair = Pair(
            reference_id="reference",
            molecule_id="candidate",
            label="candidate",
            match_status="matched",
            **result,
        )
        self.assertEqual(pair.comparison, "better")
        self.assertEqual(pair.reference_values, ["10"])
        self.assertEqual(pair.fold_change, 5.0)

    def test_controller_cpu_worker_ic50_confirmed_context_fixture(self):
        reference = Observation(metric_id="IC50", value="10", unit="nM").model_dump()
        candidate = Observation(metric_id="IC50", value="1", unit="nM").model_dump()
        result = compare_observations(
            [reference], [candidate], "IC50", "lower", [], True
        )
        self.assertEqual(result["comparison"], "better")
        self.assertEqual(result["fold_change"], 10.0)
        self.assertEqual(result["reference_values"], ["10"])
        self.assertEqual(result["candidate_values"], ["1"])
        self.assertEqual(result["evidence_basis"], "user_confirmed")


if __name__ == "__main__":
    unittest.main()
