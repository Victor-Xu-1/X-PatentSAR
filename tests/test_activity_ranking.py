"""Presentation-only, tied-value project terciles; no chemistry inference."""

import unittest

from patent_sar_extractor.web.activity_rank_values import rank_value
from patent_sar_extractor.web.activity_ranking import RankBudget, RankDistribution


def profile(values, name="IC50", unit="nM", assay="binding"):
    distribution = RankDistribution(RankBudget())
    for value in values:
        distribution.observe(value)
    return distribution.profile(name, unit, assay)


class ActivityRankingTests(unittest.TestCase):
    def test_numeric_lower_and_higher_directions_keep_exact_terciles(self):
        low = profile(range(1, 10))
        high = profile(range(1, 10), name="pIC50", unit=None)
        self.assertEqual(
            (low.direction, low.strong_boundary, low.medium_boundary), ("lower", 3, 6)
        )
        self.assertEqual(
            (high.direction, high.strong_boundary, high.medium_boundary),
            ("higher", 7, 4),
        )

    def test_source_grade_order_and_weighted_ties_do_not_split_values(self):
        plus = profile(
            ["+++"] * 12 + ["++"] + ["+"] * 3,
            name="Anti-proliferation activity grade",
            unit=None,
        )
        letter = profile(
            ["A"] * 4 + ["B"] * 15 + ["C"] * 25 + ["D"] * 26,
            name="Protein degradation grade",
            unit=None,
            assay="Western blot",
        )
        self.assertEqual(
            (plus.direction, plus.strong_boundary, plus.medium_boundary),
            ("higher", 3, 2),
        )
        self.assertEqual(
            (letter.direction, letter.strong_boundary, letter.medium_boundary),
            ("lower", 1, 2),
        )
        self.assertEqual(letter.eligible, 70)

    def test_all_equal_and_two_values_do_not_manufacture_distinct_tiers(self):
        same = profile(["+++"] * 16, name="HTRF grade", unit=None)
        two = profile([1, 1, 9])
        self.assertEqual(
            (same.distinct, same.strong_boundary, same.medium_boundary), (1, 3, 3)
        )
        self.assertEqual(
            (two.distinct, two.strong_boundary, two.medium_boundary), (2, 1, 1)
        )

    def test_censored_missing_invalid_and_nonfinite_values_are_never_ranked(self):
        for value in (
            None,
            True,
            "",
            "<10",
            ">1000",
            "≤2",
            "1-3",
            "10 nM",
            "NaN",
            "Infinity",
            float("inf"),
            "++?",
            "AB",
        ):
            with self.subTest(value=value):
                self.assertIsNone(rank_value(value))
        self.assertEqual(rank_value(" 1.2e-3 "), ("numeric", 0.0012))
        self.assertEqual(rank_value("++"), ("plus", 2.0))
        self.assertEqual(rank_value("A"), ("letter", 0.0))
        self.assertEqual(rank_value(0), ("numeric", 0.0))

    def test_unknown_and_mixed_semantics_do_not_guess_a_direction(self):
        unknown = profile([1, 2, 3], name="Assay signal", unit=None)
        mixed = profile([1, "++", 3])
        letter = profile(["A", "B", "C"], name="Response category", unit=None)
        for result in (unknown, mixed, letter):
            self.assertEqual(result.direction, "unknown")
            self.assertIsNone(result.strong_boundary)
            self.assertIsNone(result.medium_boundary)

    def test_supported_percent_and_competitive_htrf_direction_are_explicit(self):
        htrf = profile(
            [0.1, 0.2, 0.3], name="Cereblon HTRF ratio", unit=None, assay="HTRF"
        )
        percent = profile([10, 50, 90], name="Inhibition", unit="%")
        self.assertEqual(htrf.direction, "lower")
        self.assertEqual(percent.direction, "higher")

    def test_shared_unique_value_budget_disables_only_color_not_source_rows(self):
        budget = RankBudget(remaining=2)
        first = RankDistribution(budget)
        for value in (1, 2, 3):
            first.observe(value)
        scale = first.profile("IC50", "nM", "binding")
        self.assertEqual(scale.rule, "limit")
        self.assertEqual(scale.direction, "unknown")
        self.assertIsNone(scale.strong_boundary)

    def test_distribution_is_independent_of_observation_order(self):
        values = [1, 1, 2, 3, 4, 6, 6, 8, 9]
        self.assertEqual(profile(values), profile(list(reversed(values))))
