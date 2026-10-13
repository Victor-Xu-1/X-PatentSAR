"""Generic interval proofs; no patent identifiers, midpoint values or model calls."""

from __future__ import annotations

import copy
import itertools
import unittest
from decimal import Decimal

from test_sar_statistics import CONTEXT, compare, observation

from patent_sar_extractor.core.sar.statistics import compare_observations
from patent_sar_extractor.core.sar.study_priority import pareto_fronts
from patent_sar_extractor.core.sar.values import compare_values, parse_value


class IntervalBoundaryTests(unittest.TestCase):
    def test_archived_boundary_rule_remains_read_only_and_explicit(self):
        for left, right, expected in (
            (">10", "<10", "indeterminate"),
            (">20", "<10", "better"),
        ):
            result = compare_observations(
                [observation(left)],
                [observation(right)],
                "potency",
                "lower",
                [],
                False,
                open_bounds=False,
            )
            self.assertEqual(result["comparison"], expected)
            self.assertIsNone(result["fold_change"])

    def test_open_touching_limits_prove_direction_without_inventing_a_fold(self):
        cases = (
            (">10", "<10"),
            (">=10", "<10"),
            (">10", "<=10"),
            ("10", "<10"),
            (">10", "10"),
            ("[10,20]", "[1,10)"),
            ("(10,20]", "[1,10]"),
            ("[1e-9,2e-9]", "<1e-9"),
        )
        for high, low in cases:
            for direction, status in (("lower", "better"), ("higher", "worse")):
                with self.subTest(high=high, low=low, direction=direction):
                    left, right = [observation(high)], [observation(low)]
                    before = copy.deepcopy((left, right))
                    result = compare(left, right, direction=direction)
                    self.assertEqual(result["comparison"], status)
                    self.assertEqual(result["evidence_basis"], "recorded_context")
                    self.assertIsNone(result["fold_change"])
                    self.assertEqual((left, right), before)
                    self.assertEqual(result["reference_values"], [high])
                    self.assertEqual(result["candidate_values"], [low])

    def test_closed_touching_overlapping_missing_and_conflicting_remain_unresolved(
        self,
    ):
        for left, right in ((">=10", "<=10"), ("[1,10]", "[10,20]"), ("<10", "<10")):
            with self.subTest(left=left, right=right):
                result = compare([observation(left)], [observation(right)])
                self.assertEqual(result["comparison"], "indeterminate")
                self.assertIsNone(result["fold_change"])
        for context in ({}, {**CONTEXT, "duration": "different"}):
            result = compare(
                [observation(">10")], [observation("<10", context=context)]
            )
            self.assertNotIn(result["comparison"], {"better", "worse", "equal"})
        self.assertEqual(
            compare([observation(">10")], [observation("<10", unit="uM")])[
                "comparison"
            ],
            "context_mismatch",
        )
        self.assertEqual(
            compare([observation("ND")], [observation("<10")])["comparison"], "missing"
        )

    def test_pareto_uses_the_same_interval_proof_in_both_directions(self):
        values = {
            "above": (parse_value(">10", {}),),
            "below": (parse_value("<10", {}),),
        }
        for direction, expected in (
            ("lower", {"below": 1, "above": 2}),
            ("higher", {"above": 1, "below": 2}),
        ):
            with self.subTest(direction=direction):
                self.assertEqual(
                    pareto_fronts(
                        values, [{"direction": direction, "grade_order": []}]
                    ),
                    expected,
                )
        closed = {
            "above": (parse_value(">=10", {}),),
            "below": (parse_value("<=10", {}),),
        }
        self.assertEqual(
            pareto_fronts(closed, [{"direction": "lower", "grade_order": []}]),
            {"above": 1, "below": 1},
        )

    def test_finite_integer_endpoint_intervals_against_independent_quarter_grid(self):
        # Integer endpoints plus all quarter-points independently cover equality,
        # strict separation and every overlap for these bounded real intervals.
        cases = []
        grid = [Decimal(i) / 4 for i in range(-8, 9)]
        for low, high in itertools.combinations(range(-2, 3), 2):
            for lc, uc in itertools.product((False, True), repeat=2):
                raw = f"{'[' if lc else '('}{low},{high}{']' if uc else ')'}"
                points = [
                    p
                    for p in grid
                    if (p > low or lc and p == low) and (p < high or uc and p == high)
                ]
                cases.append((raw, parse_value(raw, {}), points))
        for left_raw, left, left_points in cases:
            for right_raw, right, right_points in cases:
                expected = (
                    "better"
                    if max(right_points) < min(left_points)
                    else "worse"
                    if min(right_points) > max(left_points)
                    else "indeterminate"
                )
                with self.subTest(reference=left_raw, candidate=right_raw):
                    self.assertEqual(
                        compare_values(left, right, "lower", {})[0], expected
                    )


if __name__ == "__main__":
    unittest.main()
