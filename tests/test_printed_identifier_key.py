"""Proof keys preserve complete printed IDs and cannot mine digits from hashes."""

import unittest

from patent_sar_extractor.core.binding_labels import _cpd_label_key
from patent_sar_extractor.core.pipeline_rules import _label_key


class PrintedIdentifierKeyTests(unittest.TestCase):
    def test_complete_dash_prefix_suffix_and_zero_are_preserved(self):
        for value, expected in (
            ("Compound 1-2-3AB", "1-2-3AB"),
            ("A-001B", "A-001B"),
            ("Compound 0", "0"),
            ("Cmpd 42", "42"),
        ):
            for key in (_label_key, _cpd_label_key):
                with self.subTest(value=value, key=key.__name__):
                    self.assertEqual(key(value), expected)

    def test_hash_prose_composite_or_nonprinted_ids_are_not_inferred(self):
        for value in (
            "source-structure:fb73ed118d6a",
            "unrelated 42 text",
            "Compound 1/2",
            "1_2",
        ):
            for key in (_label_key, _cpd_label_key):
                with self.subTest(value=value, key=key.__name__):
                    self.assertEqual(key(value), "")
