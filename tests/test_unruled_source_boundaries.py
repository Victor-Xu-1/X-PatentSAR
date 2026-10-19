"""Original row extents and explicit section boundaries, not numeric sequence."""

import unittest

from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.source_section_roles import section_body_boundary
from patent_sar_extractor.core.unruled_structure_proof import unruled_source_inventory


def original_region(payload):
    return next(
        s["source"]
        for s in payload["source_sections"]
        if s["role"] == "unruled_structure_region"
    )


class UnruledSourceBoundaryTests(UnruledStructureControls, unittest.TestCase):
    def test_uncertain_boundary_cannot_extend_nonfinal_ownership_in_either_layout(self):
        for ruled in (False, True):

            def doubtful_section(page, _structures, *, ruled=ruled):
                if ruled:
                    for x in (40, 175, 380):
                        page.draw_line((x, 65), (x, 330))
                    for y in (65, 100, 210, 330):
                        page.draw_line((40, y), (380, y))
                # An explicit section cue overlaps a known diagram. It cannot
                # truncate original facts or extend the old nonfinal role.
                page.insert_text((40, 260), "Compound 901: Preparation", fontsize=8)

            with self.subTest(ruled=ruled):
                _, payload = self.run_binding(
                    ["73", "28"],
                    title="Table 12. Intermediates",
                    mutate_page=doubtful_section,
                )
                issues, nonfinal = unruled_source_inventory(
                    payload["source_sections"], payload["source_reference_scope"], []
                )
                self.assertEqual(nonfinal, {"S0"})
                self.assertTrue(
                    any(
                        issue["reason"] == "unproved_original_column_boundary"
                        for issue in issues
                    )
                )
                raw = next(
                    s["source"]
                    for s in payload["source_sections"]
                    if s["role"]
                    in {"unruled_structure_region", "structure_column_anchor"}
                )
                self.assertEqual({d["id"] for d in raw["page_diagrams"]}, {"S0", "S1"})
                self.assertTrue(coverage_errors(payload))

    def test_section_boundary_requires_an_explicit_title_not_a_row_label_or_reference(
        self,
    ):
        for raw, expected in (
            ("Compound 73", False),
            ("Intermediate 73", False),
            ("Compound 73: first eluting isomer", False),
            ("Prepared in analogy to Compound 73", False),
            ("Compound 73: Preparation", True),
            ("Synthesis of Compound 73", True),
            ("Example 73: Pharmacokinetic assay", True),
            ("化合物73: 制备", True),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(section_body_boundary(raw) is not None, expected)

    def test_generated_scan_keeps_top_and_bottom_alignment_without_a_distance_fallback(
        self,
    ):
        for offset in (-34, 42):
            with self.subTest(offset=offset):
                result, payload = self.run_binding(
                    ["73", "28"], raster=True, label_baseline_offset=offset
                )
                self.assertEqual(
                    {b["cpd"] for b in result["compound_catalog"]["entries"]},
                    {"Compound 73", "Compound 28"},
                )
                self.assertEqual(coverage_errors(payload), [])

    def test_top_aligned_original_word_extent_matches_without_centre_inside_drawing(
        self,
    ):
        result, payload = self.run_binding(["73", "28"], label_baseline_offset=-34)
        self.assertEqual(
            {
                b["cpd"]: b["structure_id"]
                for b in result["compound_catalog"]["entries"]
            },
            {"Compound 73": "S0", "Compound 28": "S1"},
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_bottom_aligned_original_word_extent_matches_without_centre_inside_drawing(
        self,
    ):
        result, payload = self.run_binding(["73", "28"], label_baseline_offset=42)
        self.assertEqual(
            {
                b["cpd"]: b["structure_id"]
                for b in result["compound_catalog"]["entries"]
            },
            {"Compound 73": "S0", "Compound 28": "S1"},
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_disjoint_label_is_not_stretched_or_distance_matched_to_a_drawing(self):
        result, payload = self.run_binding(["73", "28"], label_baseline_offset=-60)
        self.assertEqual(result["compound_catalog"]["entries"], [])
        self.assertTrue(coverage_errors(payload))

    def test_a_word_overlapping_two_drawing_extents_remains_ambiguous(self):
        def rival(_page, structures):
            structures.append(
                {
                    **structures[0],
                    "structure_id": "rival",
                    "structure_index": 9,
                    "bbox_pdf": [215, 184, 355, 210],
                }
            )

        result, payload = self.run_binding(
            ["73", "28"], label_baseline_offset=42, mutate_page=rival
        )
        self.assertEqual(
            {b["cpd"] for b in result["compound_catalog"]["entries"]}, {"Compound 28"}
        )
        self.assertTrue(coverage_errors(payload))

    def test_following_original_table_title_and_text_are_not_identifier_rows(self):
        def next_table(page, _structures):
            page.insert_text((40, 430), "Table 22. Assay results", fontsize=10)
            page.insert_text(
                (40, 450), "Reported values and experimental conditions", fontsize=10
            )

        result, payload = self.run_binding(["73", "28"], mutate_page=next_table)
        self.assertEqual(len(result["compound_catalog"]["entries"]), 2)
        self.assertEqual(len(original_region(payload)["labels"]), 2)
        self.assertEqual(coverage_errors(payload), [])

    def test_new_synthesis_heading_is_preserved_outside_the_original_table(self):
        def next_section(page, _structures):
            page.insert_text((40, 430), "Compound 901: Preparation", fontsize=10)
            page.insert_text(
                (40, 450), "The reaction was stirred under nitrogen.", fontsize=10
            )

        result, payload = self.run_binding(["73", "28"], mutate_page=next_section)
        self.assertEqual(len(result["compound_catalog"]["entries"]), 2)
        self.assertEqual(len(original_region(payload)["labels"]), 2)
        self.assertTrue(
            any(
                s.get("identifier") == "901" and s.get("role") == "compound_heading"
                for s in payload["source_sections"]
            )
        )
        self.assertFalse(
            any("unruled" in issue["reason"] for issue in payload["source_issues"])
        )
        self.assertTrue(
            coverage_errors(payload)
        )  # The independent missing product remains missing.

    def test_scanned_following_table_title_is_qualified_by_the_same_original_source(
        self,
    ):
        def next_table(page, _structures):
            page.insert_text((40, 430), "Table 22. Assay results", fontsize=10)
            page.insert_text(
                (40, 450), "Reported values and experimental conditions", fontsize=10
            )

        result, payload = self.run_binding(
            ["73", "28"], raster=True, mutate_page=next_table
        )
        self.assertEqual(len(result["compound_catalog"]["entries"]), 2)
        self.assertEqual(len(original_region(payload)["labels"]), 2)
        self.assertEqual(coverage_errors(payload), [])

    def test_table_reference_inside_a_drawing_is_not_a_new_region_boundary(self):
        for text in ("Table 22", "Table 22. Intermediates", "Table 22. Compounds"):

            def diagram_annotation(page, _structures, *, text=text):
                page.insert_text((240, 170), text, fontsize=7)

            with self.subTest(text=text):
                result, payload = self.run_binding(
                    ["73", "28"], mutate_page=diagram_annotation
                )
                self.assertEqual(len(result["compound_catalog"]["entries"]), 2)
                self.assertEqual(original_region(payload)["body_bottom"], 720)
                self.assertEqual(coverage_errors(payload), [])

    def test_following_independent_product_is_not_lost_or_claimed_by_the_table(self):
        def next_product(page, structures):
            page.insert_text((40, 430), "Compound 901: Preparation", fontsize=10)
            page.draw_polyline(
                [
                    (240, 485),
                    (265, 470),
                    (290, 485),
                    (290, 515),
                    (265, 530),
                    (240, 515),
                    (240, 485),
                ]
            )
            structures.append(
                {
                    "structure_id": "S901",
                    "structure_index": 2,
                    "page_no": 1,
                    "bbox_pdf": [215, 465, 355, 535],
                }
            )

        for title, expected in (
            (
                "Table 12. Compounds",
                {"Compound 73": "S0", "Compound 28": "S1", "Compound 901": "S901"},
            ),
            ("Table 12. Intermediates", {"Compound 901": "S901"}),
        ):
            with self.subTest(title=title):
                result, payload = self.run_binding(
                    ["73", "28"], mutate_page=next_product, title=title
                )
                self.assertEqual(
                    {
                        b["cpd"]: b["structure_id"]
                        for b in result["compound_catalog"]["entries"]
                    },
                    expected,
                )
                source = original_region(payload)
                self.assertEqual([d["id"] for d in source["diagrams"]], ["S0", "S1"])
                self.assertEqual(
                    [d["id"] for d in source["page_diagrams"]], ["S0", "S1", "S901"]
                )
                self.assertEqual(coverage_errors(payload), [])

    def test_known_native_raster_boundary_disagreement_cannot_shorten_the_table(self):
        def next_table(page, _structures):
            page.insert_text((40, 430), "Table 22. Assay results", fontsize=10)

        def known_different_title(page):
            page.insert_text(
                (40, 430), "Compound 901: Preparation", fontsize=10, render_mode=3
            )

        result, payload = self.run_binding(
            ["73", "28"],
            raster=True,
            mutate_page=next_table,
            native_overlay=known_different_title,
        )
        self.assertEqual(len(result["compound_catalog"]["entries"]), 2)
        self.assertEqual(original_region(payload)["body_bottom"], 720)
        self.assertTrue(coverage_errors(payload))
