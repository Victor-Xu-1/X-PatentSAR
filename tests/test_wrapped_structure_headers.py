"""Complete original multiline headers, never corrected words or inferred rows."""

import json
import unittest

from lateral_structure_support import LateralStructureControls
from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.unruled_structure_headers import unruled_header_roles
from patent_sar_extractor.web.compound_catalog import read_compound_catalog


class WrappedStructureHeaderTests(UnruledStructureControls, unittest.TestCase):
    def assert_complete(self, result, payload):
        self.assertEqual(
            {r["cpd"]: r["structure_id"] for r in result["bindings"]},
            {"Compound A17": "S0", "Compound 008-B": "S1"},
        )
        self.assertEqual(coverage_errors(payload), [])
        saved = json.loads(json.dumps(payload))
        self.assertEqual(
            len(read_compound_catalog(saved, saved["final_bindings"])[0]), 2
        )

    def test_same_literal_identifiers_in_unwrapped_original_control_remain_valid(self):
        result, payload = self.run_binding(["A17", "008-B"])
        self.assert_complete(result, payload)

    def test_both_column_headers_wrap_without_an_explicit_compound_catalogue_title(
        self,
    ):
        result, payload = self.run_binding(
            ["A17", "008-B"],
            title="Table 12",
            identifier_header="Compound\nNo.",
            structure_header="Chemical\nStructure",
        )
        self.assert_complete(result, payload)

    def test_structure_header_can_wrap_while_identifier_header_is_one_original_line(
        self,
    ):
        result, payload = self.run_binding(
            ["A17", "008-B"], structure_header="Chemical\nStructure"
        )
        self.assert_complete(result, payload)

    def test_identifier_suffix_is_not_misclassified_as_the_first_body_row(self):
        result, payload = self.run_binding(
            ["A17", "008-B"], identifier_header="Compound\nNo."
        )
        self.assert_complete(result, payload)

    def test_three_original_header_lines_keep_the_same_label_and_structure_columns(
        self,
    ):
        result, payload = self.run_binding(
            ["A17", "008-B"],
            title="Table 12",
            identifier_header="Example\nNo.",
            structure_header="Molecular\nStructure\nformula",
        )
        self.assert_complete(result, payload)

    def test_generic_number_column_uses_its_actual_wrapped_structure_and_source_title(
        self,
    ):
        result, payload = self.run_binding(
            ["A17", "008-B"],
            identifier_header="No.",
            structure_header="Chemical\nStructure",
        )
        self.assert_complete(result, payload)

    def test_generated_scan_uses_the_same_multiline_native_and_saved_consumer_contract(
        self,
    ):
        result, payload = self.run_binding(
            ["A17", "008-B"],
            raster=True,
            identifier_header="Compound\nNo.",
            structure_header="Chemical\nStructure",
        )
        self.assert_complete(result, payload)

    def test_missing_graph_in_a_wrapped_table_is_not_shifted_onto_another_identifier(
        self,
    ):
        result, payload = self.run_binding(
            ["A17", "008-B"],
            identifier_header="Compound\nNo.",
            structure_header="Chemical\nStructure",
            missing_graph=1,
        )
        self.assertEqual(
            {r["cpd"]: r["structure_id"] for r in result["bindings"]},
            {"Compound A17": "S0"},
        )
        self.assertTrue(coverage_errors(payload))

    def test_no_detector_hits_cannot_erase_a_wrapped_original_structure_source(self):
        result, payload = self.run_binding(
            ["A17", "008-B"],
            identifier_header="Compound\nNo.",
            structure_header="Chemical\nStructure",
            mutate_page=lambda _p, rows: rows.clear(),
        )
        self.assertEqual(result["bindings"], [])
        self.assertTrue(coverage_errors(payload))
        regions = [
            s
            for s in payload["source_sections"]
            if s["role"] == "unruled_structure_region"
        ]
        self.assertEqual(len(regions), 1)
        self.assertEqual(len(regions[0]["source"]["labels"]), 2)

    def test_unlabelled_wrapped_table_cannot_gain_compound_ids_from_crop_order(self):
        result, payload = self.run_binding(
            ["", ""],
            identifier_header="Compound\nNo.",
            structure_header="Chemical\nStructure",
        )
        self.assertEqual(result["bindings"], [])
        self.assertTrue(coverage_errors(payload))

    def test_unknown_original_header_word_cannot_be_dropped_to_claim_clean_success(
        self,
    ):
        _, payload = self.run_binding(
            ["A17", "008-B"], identifier_header="Compound\nUnresolved"
        )
        self.assertTrue(coverage_errors(payload))

    def test_staggered_original_header_starts_keep_both_complete_cell_readings(self):
        result, payload = self.run_binding(
            ["A17", "008-B"],
            identifier_header="Compound No.",
            structure_header="Chemical\nStructure",
            header_baselines=(94, 80),
        )
        self.assert_complete(result, payload)

    def test_unknown_qualifier_cannot_be_removed_to_create_a_chemical_structure_column(
        self,
    ):
        result, payload = self.run_binding(
            ["A17", "008-B"], structure_header="Not a\nStructure"
        )
        self.assertEqual(result["bindings"], [])
        self.assertTrue(coverage_errors(payload))

    def test_saved_header_cannot_drop_its_original_first_line_and_keep_success(self):
        _, payload = self.run_binding(
            ["A17", "008-B"],
            identifier_header="Compound\nNo.",
            structure_header="Chemical\nStructure",
        )
        header = next(
            s["source"]["header_scope"]
            for s in payload["source_sections"]
            if s["role"] == "unruled_structure_region"
        )
        for replacement in ("No.", "Compound 008-B"):
            with self.subTest(replacement=replacement):
                saved = json.loads(json.dumps(header))
                saved["nomination"][0]["text"] = replacement
                with self.assertRaises(ValueError):
                    unruled_header_roles(saved)

    def test_native_conflicting_header_cannot_be_outvoted_by_matching_pixel_reads(self):
        def conflict(page):
            page.insert_text((50, 80), "Intermediate\nNo.", fontsize=10, render_mode=3)

        result, payload = self.run_binding(
            ["A17", "008-B"],
            raster=True,
            native_overlay=conflict,
            identifier_header="Compound\nNo.",
            structure_header="Chemical\nStructure",
        )
        self.assertEqual(result["bindings"], [])
        self.assertTrue(coverage_errors(payload))

    def test_wrapped_generic_headers_cannot_invent_a_final_role_without_source_context(
        self,
    ):
        result, payload = self.run_binding(
            ["A17", "008-B"],
            title="Table 12",
            identifier_header="No.",
            structure_header="Chemical\nStructure",
        )
        self.assertEqual(result["bindings"], [])
        self.assertTrue(coverage_errors(payload))


class WrappedLateralHeaderTests(LateralStructureControls, unittest.TestCase):
    def assert_parallel(self, *, headers, nonfinal=False, raster=False):
        result, payload = self.run_case(
            ruled=False, nonfinal=nonfinal, raster=raster, headers_by_column=headers
        )
        expected = {"Compound 73", "Compound 28"}
        if not nonfinal:
            expected |= {"Compound 901A", "Compound I-003B"}
        self.assertEqual({r["cpd"] for r in result["bindings"]}, expected)
        self.assertEqual(coverage_errors(payload), [])

    def test_both_original_parallel_headers_wrap_inside_their_own_source_columns(self):
        self.assert_parallel(
            headers=(
                ("Compound\nNo.", "Chemical\nStructure"),
                ("Compound\nNo.", "Chemical\nStructure"),
            )
        )

    def test_three_line_left_header_does_not_extend_the_right_header_words(self):
        self.assert_parallel(
            headers=(
                ("Compound\nNo.", "Molecular\nStructure\nformula"),
                ("Compound No.", "Structure"),
            )
        )

    def test_wrapped_compound_column_remains_independent_of_a_nonfinal_catalogue(self):
        self.assert_parallel(
            headers=(
                ("Compound\nNo.", "Chemical\nStructure"),
                ("Compound No.", "Structure"),
            ),
            nonfinal=True,
        )

    def test_scanned_parallel_multiline_headers_keep_the_same_original_partition(self):
        self.assert_parallel(
            headers=(
                ("Compound\nNo.", "Chemical\nStructure"),
                ("Compound\nNo.", "Chemical\nStructure"),
            ),
            raster=True,
        )


if __name__ == "__main__":
    unittest.main()
