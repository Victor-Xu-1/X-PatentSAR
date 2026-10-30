"""Known technology spelling cannot become fuzzy targets, units or identifiers."""

import unittest

from patent_sar_extractor.core.activity_header_identity import (
    compact_header,
    context_conflict,
    detector_header_conflict,
    header_conflict,
)
from patent_sar_extractor.core.activity_header_sources import _column_conflict
from patent_sar_extractor.core.activity_headers import context_from_text
from patent_sar_extractor.core.assay_typography import assay_word_typography
from patent_sar_extractor.core.source_geometry import SourceLayout, SourceTokens
from patent_sar_extractor.core.source_observations import (
    source_cell_observation,
    source_observation_status,
)


class AssayTypographyTests(unittest.TestCase):
    def test_original_column_source_uses_the_same_scoped_fragment_contract(self):
        for original, fresh, conflict in (
            ("NanoBi'T", "NanoBiT DC50 nM", False),
            ("NanoBi'T", "Target: NanoBiT; DC50 nM", True),
            ("Target: NanoBi'T", "NanoBiT DC50 nM", True),
            ("nM", "NanoBiT DC50 uM", True),
            ("24 h", "NanoBiT DC50 nM 48 h", True),
        ):
            bounds = [0, 0, 200, 35]
            parts = [
                {
                    "text": original,
                    "confidence": 0.999,
                    "source": "raster",
                    "x": 45,
                    "y": 15,
                    "bbox": [4, 8, 86, 22],
                }
            ]
            tokens = SourceTokens(parts, SourceLayout((), tuple(bounds)), tuple(bounds))
            packet = source_cell_observation(tokens, bounds, native=False)
            self.assertEqual(
                source_observation_status(packet, bounds, original), "qualified"
            )
            with self.subTest(original=original, fresh=fresh):
                self.assertEqual(_column_conflict(packet, fresh), conflict)
                self.assertEqual(packet["text"], original)

    def test_detector_fragments_need_explicit_assay_header_context(self):
        for original, fresh in (
            ("NanoBi'T", "NanoBiT DC50 nM"),
            ("H'TRF", "HTRF IC50 nM"),
            ("Hi’BiT", "HiBiT EC50 uM"),
        ):
            parts = [{"text": original, "confidence": 0.999}]
            with self.subTest(original=original):
                self.assertTrue(detector_header_conflict(parts, fresh))
                self.assertFalse(
                    detector_header_conflict(parts, fresh, assay_context=True)
                )
                self.assertEqual(parts[0]["text"], original)
        self.assertTrue(
            detector_header_conflict(
                [{"text": "NanoBi'T", "confidence": 0.999}],
                "NanoBiT",
                assay_context=True,
            )
        )

    def test_fragment_context_does_not_change_named_scientific_identity(self):
        for field in ("Target", "Construct", "Cell line", "Batch", "Duration"):
            parts = [{"text": "NanoBi'T", "confidence": 0.999}]
            fresh = f"{field}: NanoBiT; IC50 nM"
            with self.subTest(field=field):
                self.assertTrue(
                    detector_header_conflict(parts, fresh, assay_context=True)
                )
        for original, fresh in (
            ("Target Q NanoBi'T", "Target R NanoBiT DC50 nM"),
            ("NanoBi'T DC50 nM", "NanoBiT DC50 uM"),
            ("NanoBi'T DC50 nM", "NanoBiT EC50 nM"),
            ("NanoBiT7", "NanoBiT DC50 nM"),
            ("Nano'Bi'T", "NanoBiT DC50 nM"),
            ("5′RNA", "5RNA DC50 nM"),
        ):
            with self.subTest(original=original, fresh=fresh):
                self.assertTrue(
                    detector_header_conflict(
                        [{"text": original, "confidence": 0.999}],
                        fresh,
                        assay_context=True,
                    )
                )

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
