"""A log-potency unit is a tenfold concentration change, not a raw-value decade."""

import unittest
from decimal import Decimal

from patent_sar_extractor.core.potency_bands import PotencyPool
from patent_sar_extractor.core.sar.values import parse_value
from patent_sar_extractor.web.activity_columns import ActivityColumnCatalog
from patent_sar_extractor.web.activity_rank_models import ActivityStrengthScale
from patent_sar_extractor.web.models import Activity
from patent_sar_extractor.web.table_query_bands import value_band


def profile(values):
    pool = PotencyPool()
    for index, raw in enumerate(values):
        pool.observe(str(index), raw)
    return pool.scale(basis="negative_log_molar")


class LogPotencyTests(unittest.TestCase):
    def test_default_basis_preserves_historical_nested_serialization(self):
        from patent_sar_extractor.web.sar.study_models import StudyResultPolicy

        pool = PotencyPool()
        for index in range(10):
            pool.observe(str(index), "1")
        concentration = ActivityStrengthScale.from_potency(pool.scale())
        historical = concentration.model_dump(exclude={"basis"})
        self.assertEqual(concentration.model_dump(), historical)
        self.assertEqual(
            ActivityStrengthScale.model_validate(historical).model_dump(), historical
        )
        policy = StudyResultPolicy(
            context_id="a" * 64,
            direction="lower",
            strength_method="tenth_decade",
            strength_scale=concentration,
        )
        self.assertEqual(policy.model_dump()["strength_scale"], historical)
        logarithmic = ActivityStrengthScale.from_potency(profile(["9"] * 10))
        self.assertEqual(logarithmic.model_dump()["basis"], "negative_log_molar")
        self.assertEqual(
            ActivityStrengthScale.model_validate_json(logarithmic.model_dump_json()),
            logarithmic,
        )

    def test_main_table_catalog_color_filters_and_metadata_use_the_same_basis(self):
        for name in ("pIC50", "pEC50", "pDC50", "pKi", "pKd"):
            with self.subTest(name=name):
                catalog = ActivityColumnCatalog()
                for index, raw in enumerate(["10"] * 9 + ["9", "8", "7", ""]):
                    catalog.observe(
                        [Activity(name=name, value=raw)], compound_id=str(index)
                    )
                metadata = catalog.columns()[0].strength_scale
                self.assertEqual(metadata.basis, "negative_log_molar")
                self.assertEqual(metadata.direction, "higher")
                self.assertEqual(metadata.anchor_exponent, -9)
                self.assertEqual(
                    [value_band(raw, metadata) for raw in ("9", "8", "7", ">8", ">=8")],
                    ["strong", "medium", "none", "strong", "none"],
                )
                for mutation in (
                    {"direction": "lower"},
                    {"strong_boundary": 9.0},
                    {"basis": "concentration"},
                ):
                    with self.assertRaises(ValueError):
                        ActivityStrengthScale.model_validate(
                            {**metadata.model_dump(), **mutation}
                        )

    def test_percent_unknown_or_conflicting_log_units_do_not_get_invented_tiers(self):
        for name, unit in (
            ("Dmax", "%"),
            ("pIC50", "nM"),
            ("log IC50", None),
            ("unknown", None),
        ):
            with self.subTest(name=name, unit=unit):
                catalog = ActivityColumnCatalog()
                for index in range(12):
                    catalog.observe(
                        [Activity(name=name, unit=unit, value="80")],
                        compound_id=str(index),
                    )
                metadata = catalog.columns()[0].strength_scale
                self.assertEqual(metadata.status, "unsupported")
                self.assertIsNone(metadata.strong_boundary)
                self.assertEqual(value_band("80", metadata), "none")

    def test_nonpositive_concentration_repeat_does_not_become_valid_by_union(self):
        pool = PotencyPool()
        for index in range(10):
            pool.observe(str(index), "1")
        pool.observe("9", "-1")
        self.assertEqual(pool.scale().status, "ambiguous")
        self.assertEqual(pool.scale().eligible, 9)
        self.assertEqual(pool.scale(basis="negative_log_molar").eligible, 10)

    def test_tenth_identity_and_exact_concentration_equivalent_boundaries(self):
        result = profile(["10"] * 9 + ["9", "8", "7", ""])
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.basis, "negative_log_molar")
        self.assertEqual(result.anchor_exponent, -9)
        self.assertEqual((result.anchor_lower, result.anchor_upper), (9, 9))
        self.assertEqual((result.strong_boundary, result.medium_boundary), (8, 7))
        self.assertEqual(
            [
                result.band(parse_value(raw, {}))
                for raw in ("10", "9", "8", "7", "0", "-1", "ND")
            ],
            ["strong", "strong", "medium", "weak", "weak", "weak", "unclassified"],
        )

    def test_fractional_anchor_uses_underlying_concentration_decade(self):
        for anchor, exponent, boundaries in (
            ("9.2", -10, (9, 8)),
            ("8.9", -9, (8, 7)),
            ("0", 0, (-1, -2)),
            ("-1.2", 1, (-2, -3)),
            ("9.000000000000000000000000000001", -10, (9, 8)),
            ("8.999999999999999999999999999999", -9, (8, 7)),
        ):
            with self.subTest(anchor=anchor):
                result = profile([anchor] * 10)
                self.assertEqual(result.status, "ready")
                self.assertEqual(result.anchor_exponent, exponent)
                self.assertEqual(
                    (result.strong_boundary, result.medium_boundary), boundaries
                )

    def test_censored_log_intervals_respect_reversed_open_bounds(self):
        for anchor, status in (
            ("(8,9]", "ready"),
            ("[8,9]", "ambiguous"),
            (">9", "ready"),
            ("<9", "ambiguous"),
        ):
            with self.subTest(anchor=anchor):
                self.assertEqual(profile(["9"] * 9 + [anchor]).status, status)
        result = profile(["9"] * 10)
        self.assertEqual(
            [
                result.band(parse_value(raw, {}))
                for raw in (">8", ">=8", "(7,8]", "[7,8]", "<=7", "<8")
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

    def test_repeat_missing_uncertainty_and_budgets_do_not_change_rank(self):
        pool = PotencyPool(limit=10)
        for _ in range(30):
            pool.observe("one", "9")
        self.assertEqual(pool.scale(basis="negative_log_molar").status, "insufficient")
        for index in range(9):
            pool.observe(str(index), "9")
        self.assertEqual(pool.scale(basis="negative_log_molar").status, "ready")
        pool.observe("one", "7")
        self.assertEqual(pool.scale(basis="negative_log_molar").status, "ambiguous")
        pool.observe("overflow", "9")
        self.assertEqual(pool.scale(basis="negative_log_molar").status, "limit")
        self.assertEqual(profile(["9"] * 9 + ["8", "unsupported"]).status, "ambiguous")

    def test_scalar_equivalence_to_exact_molar_powers(self):
        logarithms = ["11"] * 9 + ["9", "8", "7", "6", "-1"]
        logged = profile(logarithms)
        concentrations = PotencyPool()
        for index, raw in enumerate(logarithms):
            concentrations.observe(str(index), str(Decimal(1).scaleb(-int(raw))))
        molar = concentrations.scale()
        self.assertEqual(logged.anchor_exponent, molar.anchor_exponent)
        for raw in logarithms:
            self.assertEqual(
                logged.band(parse_value(raw, {})),
                molar.band(parse_value(str(Decimal(1).scaleb(-int(raw))), {})),
            )
