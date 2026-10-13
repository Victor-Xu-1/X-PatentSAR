"""Independent source discovery and conservative context roles, without models."""

import unittest
from types import SimpleNamespace

from patent_sar_extractor.core.activity_source_discovery import (
    declared_activity_source,
    discover_activity_sources,
)
from patent_sar_extractor.core.activity_source_roles import method_page_evidence
from patent_sar_extractor.core.source_section_roles import section_heading


class ActivitySourceRoleTests(unittest.TestCase):
    def test_explicit_sources_are_independent_of_assay_and_table_numbers(self):
        for source in (
            "Table 98. Binding affinity\nNo.\nIC50 (nM)\n7\n9",
            "[0531] Tabie13. Degradation\nCompound No. DC50 (nM)",
            "Example ID | EC50 (uM)\n3 | 4",
            "No.\nKi (nM)\n3 4",
        ):
            with self.subTest(source=source):
                self.assertTrue(declared_activity_source(source))
        for source in (
            "The compound was synthesized in 3 mL solvent.",
            "Binding assay results are listed in Table 98.",
            "Table 12. Synthesis reagents\n2 mmol catalyst",
        ):
            with self.subTest(source=source):
                self.assertFalse(declared_activity_source(source))

    def test_source_observation_does_not_silently_truncate(self):
        with self.assertRaises(ValueError):
            declared_activity_source("x" * 100001)

    def test_partial_native_text_cannot_hide_cached_original_source_evidence(self):
        pages = [SimpleNamespace(get_text=lambda mode: "WO 2000000000 header")]
        self.assertEqual(
            discover_activity_sources(
                pages, {"0": "Table 38. Binding assay\nNo. IC50 (nM)\n1 8"}
            ),
            [0],
        )

    def test_method_role_requires_title_and_original_procedure_not_absence_of_rows(
        self,
    ):
        method = "Example 5: Binding assay\nCells were seeded. Reagent was added."
        self.assertEqual(method_page_evidence(method), method)
        for text in (
            "Binding assay\nCells were seeded. Reagent was added.",
            "Example 5: Binding assay\nNo result table was detected.",
            method + "\n1 0.8",
            method + "\nTable 9. Results",
            method + "\nCompound 91: Product",
            method + "\nThe compound showed IC50 = 3 nM.",
            method + "\n" + "x" * 1500 + "\nTable 5. Binding",
        ):
            with self.subTest(text=text[:150]):
                self.assertEqual(method_page_evidence(text), "")

    def test_chinese_and_original_identifiers_preserve_literal_roles(self):
        for title, identifier, role in (
            ("[0042] 实施例 28：生物评价", "28", "assay_section"),
            ("化合物 28B：结合测定", "28B", "compound_heading"),
            ("Example I-29: Biological assessment", "I-29", "assay_section"),
            ("Synthesis of Example 29: HTRF assay probe", "29", "ambiguous_heading"),
            ("Example 29: Preparation", "29", "compound_heading"),
        ):
            with self.subTest(title=title):
                observed = section_heading(title)
                self.assertEqual(observed["identifier"], identifier)
                self.assertEqual(observed["role"], role)
                self.assertEqual(observed["line_text"], title)
