"""Full original multi-page structure tables, not inferred number sequences."""

import unittest

from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.binding_source_references import reference_issues
from patent_sar_extractor.core.formal_structure import coverage_errors


def continued_page(
    first,
    structures,
    *,
    gap=False,
    caption="Table 12. Continued",
    labels=("901A", "I-003B"),
    label_baseline_offset=4,
):
    doc = first.parent
    if gap:
        doc.new_page(width=520, height=720).insert_text(
            (40, 80), "Unrelated experimental section.", fontsize=10
        )
    page = doc.new_page(width=520, height=720)
    page.insert_text((40, 45), caption, fontsize=10)
    for row, label in enumerate(labels):
        centre = 130 + row * 115
        page.insert_text((60, centre + label_baseline_offset), label, fontsize=10)
        page.draw_polyline(
            [
                (230, centre - 15),
                (255, centre - 30),
                (285, centre - 15),
                (285, centre + 15),
                (255, centre + 30),
                (230, centre + 15),
                (230, centre - 15),
            ]
        )
        structures.append(
            {
                "structure_id": f"C{page.number}-{row}",
                "structure_index": len(structures),
                "page_no": page.number + 1,
                "bbox_pdf": [215, centre - 35, 355, centre + 35],
            }
        )


def same_page_part(page, structures, *, labels=("901A", "I-003B")):
    page.insert_text((40, 430), "Table 12. Continued", fontsize=10)
    for row, label in enumerate(labels):
        centre = 510 + row * 115
        page.insert_text((60, centre + 4), label, fontsize=10)
        page.draw_polyline(
            [
                (230, centre - 15),
                (255, centre - 30),
                (285, centre - 15),
                (285, centre + 15),
                (255, centre + 30),
                (230, centre + 15),
                (230, centre - 15),
            ]
        )
        structures.append(
            {
                "structure_id": f"P{row}",
                "structure_index": len(structures),
                "page_no": page.number + 1,
                "bbox_pdf": [215, centre - 35, 355, centre + 35],
            }
        )


class UnruledContinuationTests(UnruledStructureControls, unittest.TestCase):
    def test_original_abbreviated_continuation_is_not_lost_at_punctuation_boundary(
        self,
    ):
        for caption in ("Table 12 (cont.)", "Table 12. Cont."):
            with self.subTest(caption=caption):
                result, payload = self.run_binding(
                    ["73", "28"],
                    mutate_page=lambda page, structures, caption=caption: (
                        continued_page(page, structures, caption=caption)
                    ),
                )
                self.assertEqual(len(result["bindings"]), 4)
                self.assertEqual(coverage_errors(payload), [])

    def test_a_later_same_page_part_keeps_the_original_previous_page_anchor(self):
        def chain(first, structures):
            doc = first.parent
            continued_page(first, structures)
            same_page_part(doc[-1], structures, labels=("A17", "B80"))

        result, payload = self.run_binding(["73", "28"], mutate_page=chain)
        self.assertEqual(
            {b["cpd"] for b in result["bindings"]},
            {
                "Compound 73",
                "Compound 28",
                "Compound 901A",
                "Compound I-003B",
                "Compound A17",
                "Compound B80",
            },
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_same_physical_hybrid_caption_does_not_create_competing_source_regions(
        self,
    ):
        def original_caption(page):
            if page.number == 1:
                page.insert_text(
                    (41, 46), "Table 12. Continued", fontsize=10, render_mode=3
                )

        result, payload = self.run_binding(
            ["73", "28"],
            raster=True,
            mutate_page=continued_page,
            native_overlay=original_caption,
        )
        self.assertEqual(len(result["bindings"]), 4)
        self.assertEqual(coverage_errors(payload), [])

    def test_native_only_continuation_claim_cannot_be_silently_ignored(self):
        def original_caption(page):
            if page.number == 1:
                page.insert_text(
                    (40, 45), "Table 12. Continued", fontsize=10, render_mode=3
                )

        result, payload = self.run_binding(
            ["73", "28"],
            raster=True,
            mutate_page=lambda page, structures: continued_page(
                page, structures, caption="Unrelated source"
            ),
            native_overlay=original_caption,
        )
        self.assertEqual(
            {b["cpd"] for b in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertTrue(coverage_errors(payload))

    def test_same_page_headerless_part_retains_all_original_rows(self):
        result, payload = self.run_binding(["73", "28"], mutate_page=same_page_part)
        self.assertEqual(
            {b["cpd"]: b["structure_id"] for b in result["bindings"]},
            {
                "Compound 73": "S0",
                "Compound 28": "S1",
                "Compound 901A": "P0",
                "Compound I-003B": "P1",
            },
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_scanned_same_page_part_uses_original_source_not_row_order(self):
        result, payload = self.run_binding(
            ["73", "28"], raster=True, reverse=True, mutate_page=same_page_part
        )
        self.assertEqual(len(result["bindings"]), 4)
        self.assertEqual(coverage_errors(payload), [])

    def test_earlier_diagram_is_retained_as_review_not_a_publish_exception(self):
        def earlier(first, structures):
            doc = first.parent
            continued_page(first, structures)
            doc[-1].draw_rect((225, 8, 290, 28))
            structures.append(
                {
                    "structure_id": "EARLIER",
                    "structure_index": len(structures),
                    "page_no": 2,
                    "bbox_pdf": [215, 5, 355, 29],
                }
            )

        result, payload = self.run_binding(["73", "28"], mutate_page=earlier)
        self.assertEqual(
            {b["cpd"] for b in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertTrue(coverage_errors(payload))

    def test_registered_continuation_findings_are_written_once_by_source_replay(self):
        _, payload = self.run_binding(
            ["73", "28"],
            mutate_page=lambda page, structures: continued_page(
                page, structures, gap=True
            ),
        )
        self.assertEqual(
            payload["source_issues"],
            reference_issues(payload, payload["compound_catalog"]["entries"]),
        )

    def test_a_same_page_later_part_cannot_disappear_as_clean_partial_success(self):
        result, payload = self.run_binding(["73", "28"], mutate_page=same_page_part)
        self.assertTrue(len(result["bindings"]) == 4 or coverage_errors(payload))

    def test_repeated_actual_headers_are_not_an_unresolved_headerless_part(self):
        def repeated(first, structures):
            doc = first.parent
            continued_page(first, structures)
            doc[-1].insert_text((50, 80), "Compound No.", fontsize=10)
            doc[-1].insert_text((240, 80), "Structure", fontsize=10)

        result, payload = self.run_binding(["73", "28"], mutate_page=repeated)
        self.assertEqual(len(result["bindings"]), 4)
        self.assertEqual(coverage_errors(payload), [])

    def test_declared_continuation_cannot_be_clean_when_source_rows_are_missing(self):
        result, payload = self.run_binding(["73", "28"], mutate_page=continued_page)
        self.assertTrue(len(result["bindings"]) == 4 or coverage_errors(payload))

    def test_adjacent_same_original_table_without_repeated_headers_keeps_all_rows(self):
        result, payload = self.run_binding(["73", "28"], mutate_page=continued_page)
        self.assertEqual(
            {b["cpd"]: b["structure_id"] for b in result["bindings"]},
            {
                "Compound 73": "S0",
                "Compound 28": "S1",
                "Compound 901A": "C1-0",
                "Compound I-003B": "C1-1",
            },
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_generated_scanned_continuation_keeps_all_literal_ids(self):
        result, payload = self.run_binding(
            ["73", "28"], raster=True, mutate_page=continued_page
        )
        self.assertEqual(
            {b["cpd"] for b in result["bindings"]},
            {"Compound 73", "Compound 28", "Compound 901A", "Compound I-003B"},
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_letter_named_original_tables_use_the_same_continuation_contract(self):
        result, payload = self.run_binding(
            ["73", "28"],
            title="Table A. Compounds",
            mutate_page=lambda page, structures: continued_page(
                page, structures, caption="Table A. Continued"
            ),
        )
        self.assertEqual(len(result["bindings"]), 4)
        self.assertEqual(coverage_errors(payload), [])

    def test_page_gap_preserves_unresolved_rows_without_borrowing_columns(self):
        result, payload = self.run_binding(
            ["73", "28"],
            mutate_page=lambda page, structures: continued_page(
                page, structures, gap=True
            ),
        )
        self.assertEqual(
            {b["cpd"] for b in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertTrue(coverage_errors(payload))

    def test_a_new_procedure_after_the_first_table_stops_header_inheritance(self):
        def stopped(first, structures):
            first.insert_text((40, 430), "Compound 800: Preparation", fontsize=10)
            continued_page(first, structures)

        result, payload = self.run_binding(["73", "28"], mutate_page=stopped)
        self.assertEqual(
            {b["cpd"] for b in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertTrue(coverage_errors(payload))

    def test_three_page_chain_keeps_one_original_anchor_without_nested_parents(self):
        def chain(first, structures):
            doc = first.parent
            continued_page(first, structures)
            continued_page(doc[0], structures, labels=("A17", "B80"))

        result, payload = self.run_binding(
            ["73", "28"], mutate_page=chain, reverse=True
        )
        self.assertEqual(
            {b["cpd"] for b in result["bindings"]},
            {
                "Compound 73",
                "Compound 28",
                "Compound 901A",
                "Compound I-003B",
                "Compound A17",
                "Compound B80",
            },
            msg=str(payload["source_issues"]),
        )
        scopes = [
            s["source"]["header_scope"]
            for s in payload["source_sections"]
            if s["role"] == "unruled_structure_region"
        ]
        self.assertEqual(len(scopes), 3)
        self.assertTrue(all(s["anchor_scope"] == scopes[0] for s in scopes[1:]))
        self.assertEqual(coverage_errors(payload), [])

    def test_known_native_section_before_scanned_caption_blocks_inheritance(self):
        def original_section(page):
            if page.number == 1:
                page.insert_text(
                    (40, 20), "Example 800: Preparation", fontsize=9, render_mode=3
                )

        result, payload = self.run_binding(
            ["73", "28"],
            raster=True,
            mutate_page=continued_page,
            native_overlay=original_section,
        )
        self.assertEqual(
            {b["cpd"] for b in result["bindings"]}, {"Compound 73", "Compound 28"}
        )
        self.assertTrue(coverage_errors(payload))


if __name__ == "__main__":
    unittest.main()
