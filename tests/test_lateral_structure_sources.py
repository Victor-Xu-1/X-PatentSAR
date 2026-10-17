"""Independent original columns keep their own source and scientific roles."""

import json
import unittest

from lateral_structure_support import LateralStructureControls

from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.structure_declaration_scopes import declaration_scopes
from patent_sar_extractor.core.unruled_continuation_titles import qualified_table_key
from patent_sar_extractor.core.unruled_structure_headers import unruled_header_roles
from patent_sar_extractor.web.compound_catalog import read_compound_catalog


class LateralStructureSourceTests(LateralStructureControls, unittest.TestCase):
    def test_two_original_tables_keep_separate_titles_and_all_rows(self):
        result, payload = self.run_case()
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]},
            {"Compound 73", "Compound 28", "Compound 901A", "Compound I-003B"},
        )
        self.assertEqual(coverage_errors(payload), [])
        saved = json.loads(json.dumps(payload))
        self.assertEqual(
            len(read_compound_catalog(saved, saved["final_bindings"])[0]), 4
        )
        self.assertEqual(
            {
                qualified_table_key(s["source"]["header_scope"])
                for s in payload["source_sections"]
                if s["role"] == "structure_column_anchor"
            },
            {"TABLE11", "TABLEB8"},
        )
        for row in payload["final_bindings"]:
            evidence = row["numbered_table_cell_evidence"]
            expected = (
                "Table 11" if row["structure_id"].startswith("C0-") else "Table B8"
            )
            self.assertEqual(evidence["source_catalog"], expected)
            self.assertTrue(evidence["source_catalog_title"].startswith(expected + "."))

    def test_unruled_parallel_tables_keep_independent_original_sources(self):
        result, payload = self.run_case(ruled=False)
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]},
            {"Compound 73", "Compound 28", "Compound 901A", "Compound I-003B"},
        )
        self.assertEqual(coverage_errors(payload), [])
        sources = [
            s["source"]["header_scope"]
            for s in payload["source_sections"]
            if s["role"] == "unruled_structure_region"
        ]
        self.assertEqual(len(sources), 2)
        self.assertEqual(
            {qualified_table_key(s) for s in sources}, {"TABLE11", "TABLEB8"}
        )
        self.assertEqual([s["column_selection"] for s in sources], [[0, 2], [2, 4]])
        self.assertTrue(all(len(s["nomination"]) == 4 for s in sources))
        self.assertTrue(
            all("grid_axes" not in s and s["page_grids"] == [] for s in sources)
        )
        saved = json.loads(json.dumps(payload))
        self.assertEqual(
            len(read_compound_catalog(saved, saved["final_bindings"])[0]), 4
        )

    def test_unruled_nonfinal_column_does_not_hide_independent_final_compounds(self):
        result, payload = self.run_case(ruled=False, nonfinal=True)
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertEqual(coverage_errors(payload), [])
        declarations = [
            scope
            for section in payload["source_sections"]
            if section["role"] == "structure_declaration_page"
            for scope in declaration_scopes(section["source"])
        ]
        self.assertEqual({s["role"] for s in declarations}, {"compound", "nonfinal"})
        self.assertTrue(all(len(s["diagrams"]) == 2 for s in declarations))
        self.assertTrue(
            all(
                all(
                    d["id"].startswith("C0-" if s["role"] == "compound" else "C1-")
                    for d in s["diagrams"]
                )
                for s in declarations
            )
        )

    def test_unruled_independent_title_heights_do_not_merge_original_roles(self):
        for right_title_y in (30, 60):
            with self.subTest(right_title_y=right_title_y):
                result, payload = self.run_case(
                    ruled=False, nonfinal=True, right_title_y=right_title_y
                )
                self.assertEqual(
                    {r["cpd"] for r in result["bindings"]},
                    {"Compound 73", "Compound 28"},
                )
                self.assertEqual(coverage_errors(payload), [])

    def test_scanned_unruled_title_height_changes_keep_the_same_source_roles(self):
        for right_title_y in (30, 60):
            with self.subTest(right_title_y=right_title_y):
                result, payload = self.run_case(
                    ruled=False, raster=True, nonfinal=True, right_title_y=right_title_y
                )
                self.assertEqual(
                    {r["cpd"] for r in result["bindings"]},
                    {"Compound 73", "Compound 28"},
                )
                self.assertEqual(coverage_errors(payload), [])

    def test_saved_logical_window_must_rederive_from_all_original_header_and_title_words(
        self,
    ):
        _, payload = self.run_case(ruled=False)
        header = next(
            s["source"]["header_scope"]
            for s in payload["source_sections"]
            if s["role"] == "unruled_structure_region"
        )
        for field, value in (
            ("column_band", [0, 350]),
            ("column_selection", []),
            ("column_selection", [0, 4]),
            ("context_sources", []),
            ("nomination", header["nomination"][:2]),
        ):
            with self.subTest(field=field, value=value):
                saved = json.loads(json.dumps(header))
                saved[field] = value
                with self.assertRaises(ValueError):
                    unruled_header_roles(saved)

    def test_scanned_unruled_parallel_columns_keep_final_and_nonfinal_roles(self):
        for nonfinal in (False, True):
            with self.subTest(nonfinal=nonfinal):
                result, payload = self.run_case(
                    ruled=False, raster=True, nonfinal=nonfinal
                )
                self.assertEqual(len(result["bindings"]), 2 if nonfinal else 4)
                self.assertEqual(coverage_errors(payload), [])

    def test_native_conflict_in_unruled_scan_cannot_exclude_or_promote_the_wrong_column(
        self,
    ):
        result, payload = self.run_case(
            ruled=False, raster=True, nonfinal=True, native_conflict=True
        )
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertTrue(coverage_errors(payload))

    def test_shared_unruled_title_remains_global_without_independent_caption_positions(
        self,
    ):
        result, payload = self.run_case(ruled=False, shared_title=True)
        self.assertEqual(result["bindings"], [])
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(
            coverage_errors(payload),
            ["No proved printed-ID structure is available for formal processing."],
        )

    def test_unruled_later_experiment_in_neighbour_column_does_not_truncate_final_rows(
        self,
    ):
        for centre in (510, 430):
            with self.subTest(centre=centre):
                result, payload = self.run_case(
                    ruled=False, later_product=True, left_later_centre=centre
                )
                self.assertEqual(
                    {r["cpd"] for r in result["bindings"]},
                    {
                        "Compound 73",
                        "Compound 28",
                        "Compound A17",
                        "Compound 901A",
                        "Compound I-003B",
                        "Compound B80",
                    },
                )
                self.assertEqual(coverage_errors(payload), [])

    def test_original_nonfinal_role_in_one_column_does_not_change_the_other(self):
        result, payload = self.run_case(nonfinal=True)
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertEqual(coverage_errors(payload), [])
        declarations = [
            scope
            for section in payload["source_sections"]
            if section["role"] == "structure_declaration_page"
            for scope in declaration_scopes(section["source"])
        ]
        self.assertEqual({s["role"] for s in declarations}, {"compound", "nonfinal"})
        for scope in declarations:
            prefix = "C0-" if scope["role"] == "compound" else "C1-"
            self.assertEqual(len(scope["diagrams"]), 2)
            self.assertTrue(all(d["id"].startswith(prefix) for d in scope["diagrams"]))

    def test_new_experiment_in_one_column_does_not_end_the_other_column(self):
        for centre in (510, 430):
            with self.subTest(centre=centre):
                result, payload = self.run_case(
                    later_product=True, left_later_centre=centre
                )
                self.assertEqual(
                    {r["cpd"] for r in result["bindings"]},
                    {
                        "Compound 73",
                        "Compound 28",
                        "Compound A17",
                        "Compound 901A",
                        "Compound I-003B",
                        "Compound B80",
                    },
                )
                self.assertEqual(coverage_errors(payload), [])

    def test_one_original_shared_nonfinal_title_keeps_the_existing_global_role(self):
        result, payload = self.run_case(shared_title=True)
        self.assertEqual(result["bindings"], [])
        self.assertEqual(payload["source_issues"], [])
        self.assertEqual(
            coverage_errors(payload),
            ["No proved printed-ID structure is available for formal processing."],
        )

    def test_scanned_parallel_tables_keep_the_same_original_roles(self):
        for nonfinal in (False, True):
            with self.subTest(nonfinal=nonfinal):
                result, payload = self.run_case(raster=True, nonfinal=nonfinal)
                self.assertEqual(len(result["bindings"]), 2 if nonfinal else 4)
                self.assertEqual(coverage_errors(payload), [])

    def test_native_conflict_in_one_scanned_column_does_not_poison_the_other(self):
        result, payload = self.run_case(
            raster=True, nonfinal=True, native_conflict=True
        )
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertTrue(coverage_errors(payload))

    def test_saved_table_identifier_cannot_be_borrowed_from_its_neighbour(self):
        _, payload = self.run_case()
        saved = json.loads(json.dumps(payload))
        entry = next(
            r
            for r in saved["compound_catalog"]["entries"]
            if r["structure_id"].startswith("C0-")
        )
        entry["numbered_table_cell_evidence"]["source_catalog"] = "Table B8"
        with self.assertRaises(ValueError):
            reference_issues(saved, saved["compound_catalog"]["entries"])

    def test_rehashed_page_inventory_cannot_hide_a_context_neighbour(self):
        _, payload = self.run_case()
        saved = json.loads(json.dumps(payload))
        page = next(
            s
            for s in saved["source_sections"]
            if s["role"] == "structure_declaration_page"
        )
        page["source"]["page_grids"].pop()
        page["region_id"] = proof_id(page["source"])
        saved["source_reference_scope"] = reference_scope(
            saved["source_sections"],
            saved["source_reference_scope"]["original_pdf_sha256"],
        )
        saved["source_issues"] = []
        with self.assertRaises(ValueError):
            reference_issues(saved, saved["compound_catalog"]["entries"])

    def test_selected_reprint_retains_all_original_source_observations(self):
        result, payload = self.run_case(selected=True)
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        entries = payload["compound_catalog"]["entries"]
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(len(r.get("additional_sources", [])) == 1 for r in entries))
        self.assertEqual(coverage_errors(payload), [])

    def test_selected_title_cannot_erase_novel_original_identifiers(self):
        result, payload = self.run_case(selected=True, selected_novel=True)
        labels = {r["cpd"] for r in result["bindings"]}
        self.assertIn("Compound I-003B", labels)
        self.assertNotIn("Compound 73", labels)
        self.assertTrue(coverage_errors(payload))

    def test_disagreeing_original_selected_scope_cannot_enable_reprint_exclusion(self):
        result, payload = self.run_case(
            selected=True, raster=True, native_conflict=True
        )
        self.assertNotIn("Compound 73", {r["cpd"] for r in result["bindings"]})
        self.assertTrue(coverage_errors(payload))

    def test_duplicate_numbers_in_distinct_full_tables_remain_ambiguous(self):
        result, payload = self.run_case(duplicate=True)
        self.assertNotIn("Compound 73", {r["cpd"] for r in result["bindings"]})
        self.assertTrue(coverage_errors(payload))


if __name__ == "__main__":
    unittest.main()
