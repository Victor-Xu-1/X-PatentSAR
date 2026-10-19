"""Partial qualified detector runs are not complete header identities."""

import unittest

from patent_sar_extractor.core.activity_header_identity import (
    detector_header_conflict,
    header_conflict,
)


class QualifiedHeaderFragmentTests(unittest.TestCase):
    def test_weak_leading_assay_does_not_turn_target_fragment_into_whole_header(self):
        parts = [
            {"text": "Unreadable assay", "confidence": 0.3},
            {"text": "TargetX", "confidence": 0.99},
            {"text": "EC50", "confidence": 0.99},
            {"text": "nM", "confidence": 0.99},
        ]
        self.assertFalse(detector_header_conflict(parts, "AssayA TargetX EC50 (nM)"))

    def test_literal_fragment_can_keep_a_newly_observed_assay_after_target(self):
        self.assertFalse(
            detector_header_conflict(
                [{"text": "TargetY DC50 (pM)", "confidence": 0.99}],
                "TargetY AssayB DC50 (pM)",
            )
        )

    def test_full_original_identity_remains_strict_not_a_fragment(self):
        self.assertTrue(
            header_conflict("TargetX EC50 (nM)", "AssayA TargetX EC50 (nM)")
        )

    def test_known_time_cannot_be_lost_when_the_initial_unit_was_not_parenthesized(
        self,
    ):
        for old, fresh in (
            ("TargetX EC50 nM at 24 h", "TargetX EC50 nM at 48 h"),
            ("TargetX EC50 nM at 24 h", "TargetX EC50 nM"),
            ("TargetX EC50 (mutant) nM", "TargetX EC50 (wildtype) nM"),
        ):
            with self.subTest(old=old, fresh=fresh):
                self.assertTrue(header_conflict(old, fresh))

    def test_transparent_unit_wrappers_preserve_the_same_trailing_condition(self):
        self.assertFalse(
            detector_header_conflict(
                [{"text": "TargetX EC50 nM at 24 h", "confidence": 0.99}],
                "AssayA TargetX EC50 (nM) at 24 h",
            )
        )

    def test_targets_assays_units_endpoints_and_trailing_conditions_stay_known(self):
        for old, fresh in (
            ("TargetX EC50 nM", "AssayA TargetY EC50 nM"),
            ("TargetX AssayB EC50 nM", "AssayA TargetX EC50 nM"),
            ("TargetX EC50 nM", "AssayA TargetX IC50 nM"),
            ("TargetX EC50 nM", "AssayA TargetX EC50 uM"),
            ("TargetX EC50 nM at 24 h", "AssayA TargetX EC50 nM at 48 h"),
            ("TargetX EC50 nM", "AssayA TargetX-mutant EC50 nM"),
            ("TargetX EC50 nM", "AssayA TargetX2 EC50 nM"),
            ("TargetX EC50 nM", "AssayA Other-TargetX EC50 nM"),
            ("TargetX AssayA EC50 nM", "AssayA TargetX EC50 nM"),
            ("TargetX IC50 nM EC50 uM", "AssayA TargetX IC50 uM EC50 nM"),
        ):
            with self.subTest(old=old, fresh=fresh):
                self.assertTrue(
                    detector_header_conflict(
                        [{"text": old, "confidence": 0.99}],
                        fresh,
                    )
                )
