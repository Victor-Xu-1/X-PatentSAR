"""Original two-dimensional column roles, not I-prefix or row-order inference."""

import unittest

import fitz
from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.logical_column_partitions import nominate_unruled_headers
from patent_sar_extractor.core.source_document import document_sha256
from patent_sar_extractor.core.table_geometry import page_tokens
from patent_sar_extractor.core.unruled_structure_headers import (
    observe_unruled_header,
    unruled_header_roles,
)


class UnruledStructureBindingTests(UnruledStructureControls, unittest.TestCase):
    def test_complete_native_columns_keep_literal_ids_without_minimum_six_or_sequence(
        self,
    ):
        labels = ["I-007B", "3-2", "001A"]
        result, payload = self.run_binding(labels, reverse=True)
        self.assertEqual(
            {row["cpd"]: row["structure_id"] for row in result["bindings"]},
            {f"Compound {label}": f"S{i}" for i, label in enumerate(labels)},
        )
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(coverage_errors(payload), [])
        self.assertTrue(
            all(
                row["binding_rule"] == "numbered_structure_table_cell"
                for row in payload["final_bindings"]
            )
        )

    def test_two_original_numeric_rows_are_not_an_i_series_special_case(self):
        result, payload = self.run_binding(["73", "18B"])
        self.assertEqual(
            {row["cpd"] for row in result["bindings"]}, {"Compound 73", "Compound 18B"}
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_prefixed_row_labels_do_not_become_independent_synthesis_headings(self):
        result, payload = self.run_binding(["Compound 73", "Compound 28"])
        self.assertEqual(
            {b["cpd"] for b in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_generic_identifier_header_keeps_explicit_nonfinal_source_role(self):
        result, payload = self.run_binding(
            ["73", "28"],
            identifier_header="No.",
            title="Table 12. Intermediates",
        )
        self.assertEqual(result["bindings"], [])
        self.assertEqual(payload["source_issues"], [])
        source = next(
            s["source"]
            for s in payload["source_sections"]
            if s["role"] == "unruled_structure_region"
        )
        self.assertEqual(len(source["labels"]), 2)
        self.assertEqual(len(source["diagrams"]), 2)

    def test_original_header_windows_have_replayable_roles_without_invented_rules(self):
        self.run_binding(["73", "18B"])
        with fitz.open(self.root / "original.pdf") as document:
            page = document[0]
            tokens = page_tokens(page)
            nominated = nominate_unruled_headers(
                tokens, [page.rect.width, page.rect.height]
            )
            self.assertEqual(len(nominated), 1)
            scope = observe_unruled_header(
                page, tokens, nominated[0], document_sha256(document)
            )
        observed = unruled_header_roles(scope)
        self.assertEqual(observed["pairs"], ((0, 1),))
        self.assertEqual(observed["headers"], ["Compound No.", "Structure"])
        self.assertNotIn("grid_axes", scope)

    def test_missing_middle_structure_is_explicit_and_cannot_shift_other_identifiers(
        self,
    ):
        result, payload = self.run_binding(["73", "18B", "901A"], missing_graph=1)
        self.assertEqual(
            {b["cpd"]: b["structure_id"] for b in result["bindings"]},
            {"Compound 73": "S0", "Compound 901A": "S2"},
        )
        self.assertTrue(
            any(
                issue["reason"] == "unbound_original_unruled_identifier"
                for issue in payload["source_issues"]
            )
        )
        self.assertTrue(coverage_errors(payload))

    def test_unnumbered_middle_structure_is_not_assigned_a_neighbouring_identifier(
        self,
    ):
        result, payload = self.run_binding(["73", "18B", "901A"], missing_label=1)
        self.assertEqual(
            {b["cpd"]: b["structure_id"] for b in result["bindings"]},
            {"Compound 73": "S0", "Compound 901A": "S2"},
        )
        self.assertTrue(
            any(
                issue["reason"] == "unlabelled_or_ambiguous_original_unruled_structure"
                for issue in payload["source_issues"]
            )
        )
        self.assertTrue(coverage_errors(payload))

    def test_declared_intermediates_are_retained_but_not_promoted_to_final_compounds(
        self,
    ):
        result, payload = self.run_binding(
            ["73", "18B"], title="Table 12. Intermediates"
        )
        self.assertEqual(result["bindings"], [])
        self.assertEqual(payload["source_issues"], [])
        source = next(
            s["source"]
            for s in payload["source_sections"]
            if s["role"] == "unruled_structure_region"
        )
        self.assertEqual(len(source["diagrams"]), 2)
        self.assertEqual(len(source["labels"]), 2)

    def test_mixed_catalogue_is_review_not_silent_intermediate_exclusion(self):
        result, payload = self.run_binding(
            ["73", "18B"], title="Table 12. Compounds and intermediates"
        )
        self.assertEqual(result["bindings"], [])
        self.assertTrue(payload["source_issues"])

    def test_generated_scan_uses_the_same_original_columns_and_saved_proof(self):
        result, payload = self.run_binding(["73", "28"], raster=True, reverse=True)
        self.assertEqual(
            {row["cpd"]: row["structure_id"] for row in result["bindings"]},
            {"Compound 73": "S0", "Compound 28": "S1"},
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_repeated_literal_series_ids_are_not_corrected_into_missing_digits(self):
        result, payload = self.run_binding(["I-1", "I-9", "I-9", "I-4"])
        self.assertEqual(
            {b["cpd"]: b["structure_id"] for b in result["bindings"]},
            {"Compound I-1": "S0", "Compound I-4": "S3"},
        )
        self.assertTrue(payload["source_issues"])
        self.assertTrue(coverage_errors(payload))

    def test_nonaligned_distractor_id_in_another_column_is_not_an_owner(self):
        def distractor(page, _structures):
            page.insert_text((430, 154), "I-999", fontsize=10)

        result, payload = self.run_binding(["I-007B", "3-2"], mutate_page=distractor)
        self.assertEqual(
            {b["cpd"]: b["structure_id"] for b in result["bindings"]},
            {"Compound I-007B": "S0", "Compound 3-2": "S1"},
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_two_original_identifiers_in_one_row_cannot_be_nearest_tie_broken(self):
        def conflicting_label(page, _structures):
            page.insert_text((95, 154), "901", fontsize=10)

        result, payload = self.run_binding(["73", "28"], mutate_page=conflicting_label)
        self.assertEqual(
            {b["cpd"]: b["structure_id"] for b in result["bindings"]},
            {"Compound 28": "S1"},
        )
        self.assertTrue(coverage_errors(payload))

    def test_overlapping_candidates_are_not_sorted_or_count_matched_to_a_label(self):
        def rival(_page, structures):
            structures.append(
                {**structures[0], "structure_id": "rival", "structure_index": 9}
            )

        result, payload = self.run_binding(["73", "28"], mutate_page=rival)
        self.assertEqual(
            {b["cpd"]: b["structure_id"] for b in result["bindings"]},
            {"Compound 28": "S1"},
        )
        self.assertTrue(coverage_errors(payload))


if __name__ == "__main__":
    unittest.main()
