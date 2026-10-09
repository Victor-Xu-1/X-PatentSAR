"""The tenth measured source identity fixes concentration decades, not terciles."""

import unittest
from decimal import Decimal

from patent_sar_extractor.core.potency_bands import PotencyPool, concentration_unit
from patent_sar_extractor.core.sar.values import parse_value
from patent_sar_extractor.web.activity_rank_models import ActivityStrengthScale


def scale(values):
    pool = PotencyPool()
    for index, raw in enumerate(values):
        pool.observe(str(index), raw)
    return pool.scale()


class PotencyBandTests(unittest.TestCase):
    def test_user_example_and_exact_open_boundaries(self):
        result = scale(["0.1"] * 9 + ["1", "9", "10", "99", "100", "1000"])
        self.assertEqual(result.status, "ready")
        self.assertEqual((result.strong_boundary, result.medium_boundary), (10, 100))
        self.assertEqual(
            [
                result.band(parse_value(x, {}))
                for x in ["0.01", "1", "9", "10", "99", "100", "1000"]
            ],
            ["strong", "strong", "strong", "medium", "medium", "weak", "weak"],
        )

    def test_decade_not_ten_times_the_tenth_value(self):
        result = scale(["6"] * 10 + ["60", "600"])
        self.assertEqual((result.strong_boundary, result.medium_boundary), (10, 100))
        subnanomolar = scale(["0.019"] * 10)
        self.assertEqual(subnanomolar.strong_boundary, Decimal("0.1"))

    def test_repeats_do_not_fill_the_top_ten_and_order_does_not_matter(self):
        pool = PotencyPool()
        for _ in range(30):
            pool.observe("one source ID", "1")
        self.assertEqual(pool.scale().status, "insufficient")
        values = ["0.1"] * 9 + ["1", "30", "100"]
        self.assertEqual(scale(values), scale(reversed(values)))

    def test_interval_anchor_uses_order_statistic_bounds_and_never_midpoints(self):
        self.assertEqual(scale(["1"] * 9 + ["[1,9]"]).status, "ready")
        self.assertEqual(scale(["1"] * 9 + ["[1,10]"]).status, "ambiguous")
        self.assertEqual(scale(["1"] * 9 + ["[1,10)"]).status, "ready")
        self.assertEqual(scale(["1"] * 9 + ["<1"]).status, "ready")
        self.assertEqual(scale(["1"] * 9 + [">1"]).status, "ambiguous")
        # One uncertain reading cannot simply be excluded and make 10 nM the anchor.
        self.assertEqual(scale(["1"] * 9 + ["10", "unsupported"]).status, "ambiguous")

    def test_bounds_only_receive_a_color_when_the_entire_possible_range_fits(self):
        result = scale(["1"] * 10)
        self.assertEqual(
            [
                result.band(parse_value(x, {}))
                for x in ["<10", "≤10", "[10,99]", "[9,11]", "≥100", ">99"]
            ],
            [
                "strong",
                "unclassified",
                "medium",
                "unclassified",
                "weak",
                "unclassified",
            ],
        )
        for raw in ["0", "-1", "ND"]:
            self.assertEqual(result.band(parse_value(raw, {})), "unclassified")

    def test_conflicting_repeats_are_conservative_and_do_not_become_a_mean(self):
        pool = PotencyPool()
        for index in range(9):
            pool.observe(str(index), "1")
        pool.observe("ten", "1")
        pool.observe("ten", "100")
        self.assertEqual(pool.scale().status, "ambiguous")

    def test_units_are_explicit_and_scale_equivariance_preserves_physical_bands(self):
        for unit in ["M", "mM", "µM", "μM", "uM", "nM", "pM", "fM"]:
            self.assertTrue(concentration_unit(unit))
        for unit in [None, "%", "mg/mL", "ratio", "nM/kg", "unknown"]:
            self.assertFalse(concentration_unit(unit))
        nm = scale(["1"] * 10)
        um = scale(["0.001"] * 10)
        self.assertEqual(nm.strong_boundary, um.strong_boundary * 1000)

    def test_budget_and_unrepresentable_public_cutoffs_never_invent_finite_limits(self):
        pool = PotencyPool(limit=10)
        for index in range(11):
            pool.observe(str(index), "1")
        self.assertEqual(pool.scale().status, "limit")
        self.assertEqual(scale(["1e308"] * 10).status, "ambiguous")

    def test_anchor_decade_is_not_changed_by_binary_float_rounding(self):
        precise = scale(["9.999999999999999999999999999999"] * 10)
        metadata = ActivityStrengthScale.from_potency(precise)
        self.assertEqual(metadata.anchor_exponent, 0)
        self.assertEqual(
            (metadata.strong_boundary, metadata.medium_boundary), (10, 100)
        )
        from patent_sar_extractor.web.table_query_bands import value_band

        self.assertEqual(
            value_band("9.999999999999999999999999999999", metadata), "strong"
        )
        self.assertEqual(value_band("10", metadata), "medium")
        self.assertEqual(value_band("<10", metadata), "strong")
        self.assertEqual(value_band("≤10", metadata), "none")

    def test_main_catalog_counts_source_ids_not_repeated_measurements(self):
        from patent_sar_extractor.web.activity_columns import ActivityColumnCatalog
        from patent_sar_extractor.web.models import Activity

        catalog = ActivityColumnCatalog()
        catalog.observe(
            [Activity(name="IC50", unit="nM", value="1")] * 20, compound_id="one"
        )
        self.assertEqual(catalog.columns()[0].strength_scale.status, "insufficient")
        for index in range(9):
            catalog.observe(
                [Activity(name="IC50", unit="nM", value="1")], compound_id=str(index)
            )
        ready = catalog.columns()[0].strength_scale
        self.assertEqual(
            (ready.population, ready.strong_boundary, ready.medium_boundary),
            (10, 10, 100),
        )


if __name__ == "__main__":
    unittest.main()
