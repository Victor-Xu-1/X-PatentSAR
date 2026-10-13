"""Lexical page evidence distinguishes potency from amounts and disease names."""

import unittest

from patent_sar_extractor.core.page_classifier import ACTIVITY_RE


class ActivityPageSignalsTests(unittest.TestCase):
    def test_amounts_lengths_and_disease_abbreviations_are_not_activity(self):
        for text in (
            "chronic kidney disease (CKD)",
            "732 μmol, 2.20 mmol",
            "10 μm chromatography particles",
            "100nm particle diameter",
            "a synthetic reaction using 200 µmol",
        ):
            with self.subTest(text=text):
                self.assertIsNone(ACTIVITY_RE.search(text))

    def test_explicit_potency_and_standalone_molar_units_are_retained(self):
        for text in (
            "IC50 (nM)",
            "DC50",
            "EC50",
            "Ki 20 nM",
            "Kd 3 µM",
            "10 μM nigericin",
            "100nM ligand",
            "Table 3. Cellular activity",
        ):
            with self.subTest(text=text):
                self.assertIsNotNone(ACTIVITY_RE.search(text))
