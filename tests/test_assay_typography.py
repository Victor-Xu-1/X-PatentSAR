"""Known technology spelling cannot become fuzzy targets, units or identifiers."""

import unittest

from patent_sar_extractor.core.activity_header_identity import (
    compact_header,
    context_conflict,
    header_conflict,
)
from patent_sar_extractor.core.activity_headers import context_from_text
from patent_sar_extractor.core.assay_typography import assay_word_typography


class AssayTypographyTests(unittest.TestCase):
    def test_explicit_scientific_declarations_inside_headers_cannot_be_assay_aliases(
        self,
    ):
        for field in ("Target", "Construct", "Cell line", "Batch", "Duration"):
            old = f"{field}: Hi'BiT; IC50 nM"
            fresh = f"{field}: HiBiT; IC50 nM"
            with self.subTest(field=field):
                self.assertEqual(assay_word_typography(old), old)
                self.assertNotEqual(compact_header(old), compact_header(fresh))
                self.assertTrue(header_conflict(old, fresh))

    def test_one_internal_quote_in_known_assay_compares_without_changing_raw(self):
        for original, expected in (
            ("Target Q NanoBi'T DC50 nM", "Target Q NanoBiT DC50 nM"),
            ("Hi’BiT EC50 (uM)", "HiBiT EC50 (uM)"),
            ("H'TRF IC50 nM", "HTRF IC50 nM"),
            ("FA'CS Dmax (%)", "FACS Dmax (%)"),
        ):
            with self.subTest(original=original):
                self.assertEqual(assay_word_typography(original), expected)
                self.assertEqual(compact_header(original), compact_header(expected))
                self.assertFalse(header_conflict(original, expected))

    def test_prime_unknown_words_multiple_quotes_and_identifier_letters_stay_literal(
        self,
    ):
        for original in (
            "3'UTR",
            "5′RNA",
            "Target Q'",
            "HiBiT'",
            "'NanoBiT",
            "Nano'Bi'T",
            "N'anoBiT2",
            "Bi'Novel",
            "NanoBiT-A'",
            "n'M",
        ):
            self.assertEqual(assay_word_typography(original), original)

    def test_changed_endpoints_units_assays_targets_and_conditions_remain_conflicts(
        self,
    ):
        for first, second in (
            ("Target Q NanoBi'T DC50 nM", "Target Q NanoBiT EC50 nM"),
            ("Target Q NanoBi'T DC50 nM", "Target Q NanoBiT DC50 uM"),
            ("Target Q NanoBiT DC50 nM", "Target Q NanoBRET DC50 nM"),
            ("Target Q HiBiT EC50 nM", "Target R HiBiT EC50 nM"),
            ("3'RNA HiBiT EC50 nM", "3RNA HiBiT EC50 nM"),
            ("Target Q HiBiT EC50 nM 24 h", "Target Q HiBiT EC50 nM 48 h"),
        ):
            self.assertTrue(header_conflict(first, second), (first, second))

    def test_explicit_assay_typography_does_not_change_target_or_construct_identity(
        self,
    ):
        for field in ("Assay", "Target", "Construct"):
            old = context_from_text(f"Table 12. Study; {field}: NanoBi'T")
            fresh = context_from_text(f"Table 12. Study; {field}: NanoBiT")
            self.assertEqual(context_conflict(old, fresh), field != "Assay")
