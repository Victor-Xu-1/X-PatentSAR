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

    def test_later_assay_section_does_not_promote_previous_synthesis_table(self):
        for boundary in (
            "Example 9: Binding assay",
            "[0057] 实施例 9：生物评价",
            "Compound 91: Preparation",
        ):
            source = (
                "Table 12. NMR characterization\n"
                "Compound ID | Proton signals\n1 | 7.1 ppm\n"
                f"{boundary}\nCells were seeded and incubated. IC50 was determined."
            )
            with self.subTest(boundary=boundary):
                self.assertFalse(declared_activity_source(source))

    def test_later_table_does_not_lend_metric_to_previous_identifier_header(self):
        self.assertFalse(
            declared_activity_source(
                "Compound ID | Mass\n1 | 413\n"
                "Table 14. Reagents\nPrepared an IC50 assay probe with solvent."
            )
        )

    def test_real_result_table_after_section_boundary_remains_discoverable(self):
        for source in (
            (
                "Table 12. NMR\nCompound ID | Mass\n1 | 413\n"
                "Example 9: Binding assay\nCells were seeded and incubated.\n"
                "Table 99. Results\nCompound No. | IC50 (nM)\n1 | 8"
            ),
            "Example 9: Binding assay\nCompound No. | IC50 (nM)\n1 | 8",
            (
                "Table 12. NMR\nCompound ID | Mass\n1 | 413\n"
                "Table 98. Binding assay\nNo. | EC50 (nM)\n1 | 3"
            ),
        ):
            with self.subTest(source=source):
                self.assertTrue(declared_activity_source(source))

    def test_caption_only_results_are_still_nominated_for_unresolved_inventory(self):
        from patent_sar_extractor.core.activity_coverage import (
            coverage_errors,
            coverage_packet,
        )

        for source in (
            "Table 44. Binding activity\nUnreadable body",
            "[0049] Table 44\nBinding activity\nUnreadable body",
            "表 44\n药代动力学\nUnreadable body",
        ):
            with self.subTest(source=source):
                self.assertTrue(declared_activity_source(source))
        packet = coverage_packet([], [], [], discovered_pages=[3])
        self.assertTrue(any("p4" in error for error in coverage_errors(packet, [])))

    def test_real_native_document_preserves_page_scope_and_source_numbers(self):
        import fitz

        sources = (
            (
                "Table 71. NMR characterization\nCompound ID | Signals\n2 | 7.1 ppm\n"
                "Example 92: Binding assay\nCells were seeded and incubated. IC50 measured."
            ),
            "Table 87. Results\nCompound No. | IC50 (nM)\n73 | 12.4\n58 | 9.1",
            "Table 38\nBinding activity\nUnreadable body",
        )
        with fitz.open() as doc:
            for source in sources:
                page = doc.new_page()
                page.insert_text((40, 60), source, fontsize=11)
            self.assertEqual(discover_activity_sources(doc, {}), [1, 2])

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
